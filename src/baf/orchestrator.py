"""Orchestrator — ties the pipeline together.

Flow:
  1. Create (or receive) a Case row.
  2. Scene Router sets scene_type on the Case.
  3. Skill Retriever picks skills.
  4. Agent Composer designs the team (or reuses a blueprint).
  5. For each agent in the team, run it in the order implied by
     their role. (MVP uses a fixed order suited to 故障处置:
     IC → RC → FX → VF. Parallelism is left for V1.1.)
  6. Close the case: write result_summary, promote the run into
     an SOP if verification passed.

All state transitions are reflected back into Cases so the multi-dim
table shows a live timeline.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from rich.console import Console
from rich.table import Table

from .agents.base import BaseAgent, RunContext
from .agents.composer import AgentComposerAgent
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

# Catalog of domain agents keyed by `role` — Composer can pick any of these.
DOMAIN_AGENTS: dict[str, type[BaseAgent]] = {
    "incident_commander": IncidentCommanderAgent,
    "root_cause": RootCauseAgent,
    "fix": FixAgent,
    "verification": VerificationAgent,
}
# Common aliases Composer may invent — fold back onto the canonical class.
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

# For incident scene we want a deterministic order
INCIDENT_ORDER = ["incident_commander", "root_cause", "fix", "verification"]


@dataclass
class OrchestrationResult:
    case_id: str
    case_record_id: str
    scene_type: str
    severity: str | None
    passed: bool
    summary: str


class Orchestrator:
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

    # ---- entry points ----------------------------------------------
    def submit_case(self, title: str, description: str) -> OrchestrationResult:
        """Public entry: accept a new task, run the whole pipeline."""
        case_id = f"CASE_{uuid.uuid4().hex[:10]}"
        record_id = self.storage.create_record(
            TableName.CASES,
            {
                "task_id": case_id,
                "title": title,
                "description": description,
                "scene_type": "",
                "severity": "",
                "status": "待识别",
                "created_at": time.time(),
            },
        )
        console.rule(f"[bold cyan]新 Case {case_id}")
        console.print(f"[dim]title:[/dim] {title}")
        console.print(f"[dim]desc :[/dim] {description[:160]}{'…' if len(description)>160 else ''}")

        return self._run_pipeline(case_id, record_id, description)

    # ---- internals -------------------------------------------------
    def _run_pipeline(
        self, case_id: str, record_id: str, description: str
    ) -> OrchestrationResult:
        ctx = RunContext(
            case_id=case_id, case_record_id=record_id, description=description
        )

        # 1) scene routing
        self._update_status(record_id, "识别中")
        router = SceneRouterAgent(self.llm, self.storage)
        r1 = router.run(ctx)
        self._print_step(router, r1.output)
        if r1.status != "ok":
            return self._fail(ctx, f"scene routing error: {r1.error_msg}")
        self.storage.update_record(
            TableName.CASES,
            record_id,
            {
                "scene_type": ctx.scene_type,
                "scene_confidence": r1.output.get("confidence"),
                "status": "编组中",
            },
        )

        # 2) skill retrieval
        retriever = SkillRetrieverAgent(self.llm, self.storage)
        r2 = retriever.run(ctx)
        self._print_step(retriever, r2.output)

        # 3) agent composition
        composer = AgentComposerAgent(self.llm, self.storage)
        r3 = composer.run(ctx)
        self._print_step(composer, r3.output)
        team_roles = [t.get("role") for t in ctx.team]
        self.storage.update_record(
            TableName.CASES,
            record_id,
            {
                "agent_team": team_roles,
                "status": "执行中",
            },
        )

        # 4) execute team — for 故障处置 use fixed order
        execution_order = self._plan_execution_order(ctx.scene_type or "", team_roles)
        role_spec_by_role = {t.get("role"): t for t in ctx.team}
        for role in execution_order:
            canonical = _ROLE_ALIASES.get(role, role)
            cls = DOMAIN_AGENTS.get(canonical)
            if cls is None:
                # Unknown role — spin up a generic skill-driven agent.
                spec = role_spec_by_role.get(role) or {"role": role}
                agent: BaseAgent = GenericAgent(self.llm, self.storage, role_spec=spec)
            else:
                agent = cls(self.llm, self.storage)
            res = agent.run(ctx)
            self._print_step(agent, res.output)
            if res.status != "ok":
                return self._fail(ctx, f"agent {role} failed: {res.error_msg}")

            # write severity back to Cases once IC decides
            if role == "incident_commander" and ctx.severity:
                self.storage.update_record(
                    TableName.CASES,
                    record_id,
                    {"severity": ctx.severity},
                )

        # 5) close the case
        verification = ctx.findings.get("verification", {}) or {}
        passed = bool(verification.get("passed", False))
        summary = verification.get("summary") or ctx.findings.get("root_cause", "")
        self.storage.update_record(
            TableName.CASES,
            record_id,
            {
                "status": "已完成" if passed else "已失败",
                "result_summary": summary,
                "closed_at": time.time(),
            },
        )

        # 6) Sprint C: delegate sinking + EWMA to Evolution
        try:
            distill = self.evolution.distill(ctx, passed=passed)
            if passed and distill.sop_id:
                self.storage.update_record(
                    TableName.CASES, record_id, {"sop_ref": distill.sop_id}
                )
                console.print(f"[green]📌  SOP 已沉淀:[/green] {distill.sop_id}")
                if distill.new_skills:
                    console.print(
                        f"[cyan]✨ 自蒸馏技能:[/cyan] {', '.join(distill.new_skills)}"
                    )
        except Exception as e:
            console.print(f"[yellow]Evolution 失败 (非致命): {e}[/yellow]")

        console.rule(f"[bold green]Case {case_id} → {'PASSED' if passed else 'FAILED'}")
        return OrchestrationResult(
            case_id=case_id,
            case_record_id=record_id,
            scene_type=ctx.scene_type or "",
            severity=ctx.severity,
            passed=passed,
            summary=summary,
        )

    # ---- helpers ---------------------------------------------------
    def _plan_execution_order(self, scene: str, team_roles: list[str]) -> list[str]:
        if scene == "故障处置":
            # respect canonical order; include any extra roles at the end
            ordered = [r for r in INCIDENT_ORDER if r in team_roles]
            leftovers = [r for r in team_roles if r not in ordered]
            return ordered + leftovers
        return team_roles

    def _update_status(self, record_id: str, status: str) -> None:
        self.storage.update_record(TableName.CASES, record_id, {"status": status})

    def _fail(self, ctx: RunContext, msg: str) -> OrchestrationResult:
        console.print(f"[bold red]FAIL[/bold red] {msg}")
        self.storage.update_record(
            TableName.CASES,
            ctx.case_record_id,
            {"status": "已失败", "result_summary": msg[:300]},
        )
        return OrchestrationResult(
            case_id=ctx.case_id,
            case_record_id=ctx.case_record_id,
            scene_type=ctx.scene_type or "",
            severity=ctx.severity,
            passed=False,
            summary=msg,
        )

    def _print_step(self, agent: BaseAgent, output: dict[str, Any]) -> None:
        t = Table(show_header=False, box=None, padding=(0, 1))
        t.add_column(style="bold magenta", justify="right", width=18)
        t.add_column(style="white")
        t.add_row(agent.display_name, _pretty(output))
        console.print(t)

    # SOP sinking + EWMA are now handled by `Evolution.distill()`.
    # See `src/baf/evolution/distill.py`.


def _pretty(obj: Any, max_len: int = 300) -> str:
    import json
    try:
        s = json.dumps(obj, ensure_ascii=False)
    except Exception:
        s = str(obj)
    return s if len(s) <= max_len else s[: max_len - 1] + "…"
