"""Async streaming orchestrator (DMSAS_Design.md §三.亮点 5 & 6).

Mirrors the sync `Orchestrator` but exposes the run as an async iterator
of `Event` objects, supports tick-based scheduling with `asyncio.gather`
parallelism for `is_concurrency_safe` agents, can resume from
`get_max_tick(case_id) + 1` on restart, and dispatches to the Court for
high-risk cases.

Backwards compat: the existing sync `Orchestrator.submit_case` is kept
intact (used by the CLI's `run` / `run-demo` / tests) — this module is
*additive*. Use it via `baf run-stream <desc> --mock` (added below).
"""
from __future__ import annotations

import asyncio
import time
import uuid
from dataclasses import dataclass
from typing import Any, AsyncIterator, Iterable

from rich.console import Console

from .agents.base import BaseAgent, RunContext
from .agents.composer import AgentComposerAgent
from .agents.court import CourtAgent, Verdict
from .agents.fix import FixAgent
from .agents.generic import GenericAgent
from .agents.incident_commander import IncidentCommanderAgent
from .agents.root_cause import RootCauseAgent
from .agents.scene_router import SceneRouterAgent
from .agents.skill_retriever import SkillRetrieverAgent
from .agents.verification import VerificationAgent
from .evolution.distill import Evolution
from .hooks.approvals import ApprovalRegistry
from .llm.client import LLMClient
from .storage.backend import StorageBackend, TableName

console = Console()

DOMAIN_AGENTS: dict[str, type[BaseAgent]] = {
    "incident_commander": IncidentCommanderAgent,
    "root_cause": RootCauseAgent,
    "fix": FixAgent,
    "verification": VerificationAgent,
}
_ROLE_ALIASES = {
    "verifier": "verification",
    "result_verifier": "verification",
    "qa": "verification",
    "rca": "root_cause",
    "root_cause_agent": "root_cause",
    "incident_coordinator": "incident_commander",
    "commander": "incident_commander",
    "fix_agent": "fix",
    "repair": "fix",
}

MAX_TICKS = 20
HIGH_RISK_SCENES = {"故障处置"}    # default fallback if Composer doesn't tag


@dataclass
class Event:
    type: str                      # perception | composed | tick_done | court | done | error
    payload: Any
    case_id: str = ""
    tick: int = 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "case_id": self.case_id,
            "tick": self.tick,
            "payload": self.payload,
        }


class StreamOrchestrator:
    """Async generator pipeline.

    Usage:
        orch = StreamOrchestrator(llm, storage)
        async for ev in orch.run_case_stream(case_id):
            ...
    """

    def __init__(
        self,
        llm: LLMClient,
        storage: StorageBackend,
        *,
        approval_registry: ApprovalRegistry | None = None,
        evolution: Evolution | None = None,
    ):
        self.llm = llm
        self.storage = storage
        self.approvals = approval_registry or ApprovalRegistry(storage)
        self.evolution = evolution or Evolution(storage)

    # ---- entry point ----------------------------------------------
    async def submit_case_stream(
        self, title: str, description: str
    ) -> AsyncIterator[Event]:
        case_id = f"CASE_{uuid.uuid4().hex[:10]}"
        record_id = self.storage.create_record(
            TableName.CASES,
            {
                "task_id": case_id,
                "title": title,
                "description": description,
                "status": "待识别",
                "created_at": time.time(),
            },
        )
        async for ev in self.run_case_stream(case_id, record_id, description):
            yield ev

    async def run_case_stream(
        self,
        case_id: str,
        record_id: str | None = None,
        description: str | None = None,
    ) -> AsyncIterator[Event]:
        # resume support: rehydrate context from storage if not supplied
        if record_id is None or description is None:
            cases = self.storage.list_records(
                TableName.CASES, where={"task_id": case_id}, limit=1
            )
            if not cases:
                yield Event("error", {"message": f"unknown case_id={case_id}"}, case_id=case_id)
                return
            row = cases[0]
            record_id = row["_id"]
            description = row.get("description", "")

        ctx = RunContext(case_id=case_id, case_record_id=record_id, description=description)
        start_tick = self.storage.get_max_tick(case_id)
        ctx.current_tick = start_tick

        # Already-rehydrated trace? stitch findings back from previous runs
        if start_tick > 0:
            self._rehydrate_findings(ctx)
            yield Event("resumed", {"from_tick": start_tick}, case_id=case_id, tick=start_tick)

        # ===== L1 — Perception =====
        ctx.current_tick = max(start_tick, 0) + 1
        if not ctx.scene_type:
            self._update_status(record_id, "识别中")
            r1 = await SceneRouterAgent(self.llm, self.storage).run_async(ctx)
            yield Event("perception", r1.output, case_id=case_id, tick=ctx.current_tick)
            if r1.status != "ok":
                yield self._fail(ctx, f"perception: {r1.error_msg}")
                return
            self.storage.update_record(
                TableName.CASES, record_id,
                {"scene_type": ctx.scene_type, "status": "编组中",
                 "scene_confidence": r1.output.get("confidence")},
            )
            ctx.risk_tier = self._infer_risk_tier(ctx.scene_type, ctx.description)

        # ===== L2 — Skill retrieval + Composition =====
        ctx.current_tick += 1
        retriever = SkillRetrieverAgent(self.llm, self.storage)
        composer = AgentComposerAgent(self.llm, self.storage)
        # both are concurrency-safe — gather them
        r2, _ = await asyncio.gather(
            retriever.run_async(ctx),
            asyncio.sleep(0),  # placeholder; composer uses retriever output, run sequential below
        )
        yield Event("skills", r2.output, case_id=case_id, tick=ctx.current_tick)

        ctx.current_tick += 1
        r3 = await composer.run_async(ctx)
        team_roles = [t.get("role") for t in ctx.team]
        self.storage.update_record(
            TableName.CASES, record_id,
            {"agent_team": team_roles, "status": "执行中"},
        )
        yield Event("composed", r3.output, case_id=case_id, tick=ctx.current_tick)

        # ===== L3 — Tick scheduler =====
        execution_order = self._plan_execution_order(ctx.scene_type or "", team_roles)
        role_spec_by_role = {t.get("role"): t for t in ctx.team}

        # group consecutive concurrency-safe agents into one tick
        for batch in self._batch_by_concurrency(execution_order, role_spec_by_role):
            ctx.current_tick += 1
            agents = [
                self._instantiate_agent(role, role_spec_by_role) for role in batch
            ]
            results = await asyncio.gather(
                *[a.run_async(ctx) for a in agents], return_exceptions=True
            )
            ok = True
            for idx, (role, res) in enumerate(zip(batch, results)):
                if isinstance(res, Exception):
                    yield self._fail(ctx, f"{role} crashed: {res}")
                    return
                if res.status != "ok":
                    yield self._fail(ctx, f"{role} failed: {res.error_msg}")
                    return
                # severity feedback once IC resolves
                if role == "incident_commander" and ctx.severity:
                    self.storage.update_record(
                        TableName.CASES, record_id, {"severity": ctx.severity},
                    )
                # destructive agents → request approval
                if agents[idx].is_destructive:
                    card_id = self.approvals.request(
                        case_id=ctx.case_id,
                        agent_run_id=res.run_id or "",
                        payload={
                            "role": role,
                            "fix_steps": ctx.findings.get("fix_steps", []),
                            "fix_risk": ctx.findings.get("fix_risk", "中"),
                        },
                    )
                    yield Event(
                        "approval_requested",
                        {"role": role, "card_id": card_id},
                        case_id=case_id, tick=ctx.current_tick,
                    )
                    self._update_status(record_id, "待审批")
                    decision = await asyncio.to_thread(
                        self.approvals.wait_for, card_id,
                    )
                    yield Event(
                        "approval_resolved",
                        {"card_id": card_id, "status": decision.status,
                         "note": decision.note},
                        case_id=case_id, tick=ctx.current_tick,
                    )
                    if decision.status != "approved":
                        yield self._fail(ctx, f"approval {decision.status}: {decision.note}")
                        return
                    self._update_status(record_id, "执行中")
            yield Event(
                "tick_done",
                {"tick": ctx.current_tick, "roles": batch},
                case_id=case_id, tick=ctx.current_tick,
            )
            if not ok:
                break

        # ===== L4 — Court =====
        ctx.current_tick += 1
        court = CourtAgent(self.llm, self.storage)
        verdict: Verdict = await court.adjudicate(ctx)
        yield Event("court", verdict.to_dict(), case_id=case_id, tick=ctx.current_tick)

        # ===== L5 — Evolution =====
        if verdict.passed:
            ctx.current_tick += 1
            distill = self.evolution.distill(ctx, passed=True)
            yield Event(
                "memorized",
                {"sop_id": distill.sop_id, "new_skills": distill.new_skills},
                case_id=case_id, tick=ctx.current_tick,
            )
        else:
            self.evolution.distill(ctx, passed=False)

        self.storage.update_record(
            TableName.CASES, record_id,
            {
                "status": "已完成" if verdict.passed else "已失败",
                "result_summary": verdict.summary[:300],
                "closed_at": time.time(),
            },
        )
        yield Event(
            "done",
            {"passed": verdict.passed, "summary": verdict.summary},
            case_id=case_id, tick=ctx.current_tick,
        )

    # ---- helpers --------------------------------------------------
    def _instantiate_agent(self, role: str, role_spec_by_role: dict[str, dict]) -> BaseAgent:
        canonical = _ROLE_ALIASES.get(role, role)
        cls = DOMAIN_AGENTS.get(canonical)
        if cls is None:
            spec = role_spec_by_role.get(role) or {"role": role}
            return GenericAgent(self.llm, self.storage, role_spec=spec)
        return cls(self.llm, self.storage)

    def _batch_by_concurrency(
        self, ordered_roles: list[str], role_spec_by_role: dict[str, dict]
    ) -> Iterable[list[str]]:
        """Group adjacent concurrency-safe agents into a single tick batch."""
        batch: list[str] = []
        for role in ordered_roles:
            agent = self._instantiate_agent(role, role_spec_by_role)
            if agent.is_concurrency_safe and not agent.is_destructive:
                batch.append(role)
            else:
                if batch:
                    yield batch
                    batch = []
                yield [role]
        if batch:
            yield batch

    def _plan_execution_order(self, scene: str, team_roles: list[str]) -> list[str]:
        if scene == "故障处置":
            order = ["incident_commander", "root_cause", "fix", "verification"]
            ordered = [r for r in order if r in team_roles]
            leftovers = [r for r in team_roles if r not in ordered]
            return ordered + leftovers
        return team_roles

    def _infer_risk_tier(self, scene: str | None, description: str) -> str:
        if scene in HIGH_RISK_SCENES:
            return "high"
        if any(kw in description for kw in ("生产", "全国", "P0", "P1", "宕机")):
            return "high"
        return "low"

    def _update_status(self, record_id: str, status: str) -> None:
        self.storage.update_record(TableName.CASES, record_id, {"status": status})

    def _fail(self, ctx: RunContext, msg: str) -> Event:
        self.storage.update_record(
            TableName.CASES, ctx.case_record_id,
            {"status": "已失败", "result_summary": msg[:300], "closed_at": time.time()},
        )
        return Event("error", {"message": msg}, case_id=ctx.case_id, tick=ctx.current_tick)

    def _rehydrate_findings(self, ctx: RunContext) -> None:
        """Re-populate ctx.findings from previous AgentRuns when resuming."""
        runs = self.storage.list_records(
            TableName.AGENT_RUNS, where={"case_id": ctx.case_id}, limit=200
        )
        for r in runs:
            try:
                import json as _j
                preview = r.get("output_preview")
                if isinstance(preview, str) and preview.startswith("{"):
                    data = _j.loads(preview)
                    role = r.get("agent_role") or "?"
                    if role == "scene_router":
                        ctx.scene_type = data.get("scene_type") or ctx.scene_type
                    elif role == "incident_commander":
                        ctx.severity = data.get("severity") or ctx.severity
                    elif role == "root_cause":
                        ctx.findings["root_cause"] = data.get("root_cause", "")
                        ctx.findings["rc_evidence"] = data.get("evidence", [])
                    elif role == "fix":
                        ctx.findings["fix_steps"] = data.get("steps", [])
                        ctx.findings["fix_rollback"] = data.get("rollback", "")
            except Exception:
                continue


# ---- sync helper for tests / non-async callers ------------------
def run_case_sync(llm: LLMClient, storage: StorageBackend, title: str, description: str) -> dict:
    """Convenience: drive the stream orchestrator from sync code, return a dict summary."""
    orch = StreamOrchestrator(llm, storage)
    events: list[dict] = []

    async def _drive() -> None:
        async for ev in orch.submit_case_stream(title, description):
            events.append(ev.to_dict())

    asyncio.run(_drive())
    return {
        "events": events,
        "passed": any(e.get("type") == "done" and e["payload"].get("passed") for e in events),
    }
