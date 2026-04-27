"""Agent base class.

Every agent inherits from BaseAgent. A run() call does three things:
  1) Construct prompt from system_prompt + context
  2) Call LLM (possibly multi-turn with tools)
  3) Persist an entry in AgentRuns — this is what makes the "virtual
     organization" visible inside the Bitable.

Sprint A adds 4 metadata fields lifted from Claude Code's `buildTool()`:
  is_concurrency_safe / is_destructive / risk_tier / search_hint.
The orchestrator reads these to decide which agents can run in parallel
in the same tick, which require human approval, and to feed Composer's
two-stage skill retrieval.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Literal

from ..llm.client import LLMClient, LLMResponse
from ..storage.backend import StorageBackend, TableName


@dataclass
class RunContext:
    """Shared execution context passed between agents during one case."""
    case_id: str
    case_record_id: str
    description: str
    scene_type: str | None = None
    severity: str | None = None
    risk_tier: str = "low"                                # high/critical → Court mode
    skills: list[dict] = field(default_factory=list)      # retrieved skill records
    team: list[dict] = field(default_factory=list)        # composed agent roles
    findings: dict[str, Any] = field(default_factory=dict)  # shared scratchpad
    blackboard: dict[str, Any] = field(default_factory=dict)
    # Sprint A — tick & resume
    current_tick: int = 0
    parent_run_id: str | None = None

    def snapshot(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scene_type": self.scene_type,
            "severity": self.severity,
            "risk_tier": self.risk_tier,
            "tick": self.current_tick,
            "skills": [s.get("skill_id") for s in self.skills],
            "team": [t.get("role") for t in self.team],
            "findings_keys": list(self.findings.keys()),
        }


@dataclass
class AgentResult:
    role: str
    status: str                 # "ok" | "error" | "skipped"
    output: dict[str, Any]
    latency_ms: int = 0
    token_usage: int = 0
    error_msg: str = ""
    run_id: str = ""            # AgentRuns row id (set after persistence)
    tick: int = 0


class BaseAgent:
    role: str = "base"
    display_name: str = "Base Agent"
    system_prompt: str = ""
    temperature: float = 0.2
    json_mode: bool = True
    model: str | None = None    # None → use client default

    # ----- Sprint A metadata ----------------------------------------
    # Whether this agent's effects are confined to its own context (no
    # side-effects on shared resources). Concurrency-safe agents are
    # batched into the same `asyncio.gather` tick.
    is_concurrency_safe: bool = True
    # Destructive agents change the outside world (restart, send email,
    # write DB). They are forced through the approval registry.
    is_destructive: bool = False
    # risk_tier of the agent itself (separate from case risk_tier).
    risk_tier: Literal["low", "mid", "high", "critical"] = "low"
    # 5–10 word description shown to Composer during skill retrieval.
    search_hint: str = ""

    def __init__(self, llm: LLMClient, storage: StorageBackend):
        self.llm = llm
        self.storage = storage

    # ----- permission gate ------------------------------------------
    def check_permissions(self, ctx: "RunContext") -> Literal["allow", "block", "ask"]:
        """Return whether this agent may proceed.

        Mirrors Claude Code's `Tool.checkPermissions()`. Destructive agents
        default to `ask` so the orchestrator routes them through the
        ApprovalRegistry; everything else `allow`s.
        """
        if self.is_destructive:
            return "ask"
        return "allow"

    # ----- public ----------------------------------------------------
    def run(self, ctx: RunContext) -> AgentResult:
        t0 = time.time()
        result: AgentResult
        try:
            output = self._do(ctx)
            result = AgentResult(
                role=self.role,
                status="ok",
                output=output,
                latency_ms=int((time.time() - t0) * 1000),
                token_usage=ctx.blackboard.pop("_last_tokens", 0),
                tick=ctx.current_tick,
            )
        except Exception as e:
            result = AgentResult(
                role=self.role,
                status="error",
                output={},
                latency_ms=int((time.time() - t0) * 1000),
                error_msg=f"{e}\n{traceback.format_exc(limit=3)}",
                tick=ctx.current_tick,
            )
        result.run_id = self._record_run(ctx, result) or ""
        return result

    async def run_async(self, ctx: RunContext) -> AgentResult:
        """Async wrapper — run the (sync) `_do` in the default executor.

        Allows the orchestrator to `asyncio.gather` independent agents
        without each agent having to be re-implemented as a coroutine.
        Override in subclasses that genuinely need async I/O.
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(None, self.run, ctx)

    # ----- override --------------------------------------------------
    def _do(self, ctx: RunContext) -> dict[str, Any]:
        raise NotImplementedError

    # ----- helpers ---------------------------------------------------
    def _chat(
        self,
        messages: list[dict],
        *,
        ctx: RunContext | None = None,
        json_mode: bool | None = None,
        temperature: float | None = None,
    ) -> LLMResponse:
        resp = self.llm.chat(
            messages,
            model=self.model,
            temperature=self.temperature if temperature is None else temperature,
            json_mode=self.json_mode if json_mode is None else json_mode,
        )
        if ctx is not None:
            ctx.blackboard["_last_tokens"] = resp.total_tokens
        return resp

    def _record_run(self, ctx: RunContext, result: AgentResult) -> str | None:
        """Write one row to AgentRuns so the Bitable shows the agent timeline.

        The row is the resume-checkpoint described in design §亮点 5: every
        yield point in the orchestrator gets persisted before control
        returns to the caller, so a crashed run can be resumed by replaying
        from `max_tick + 1`.
        """
        try:
            return self.storage.create_record(
                TableName.AGENT_RUNS,
                {
                    "case_id": ctx.case_id,
                    "case_ref": ctx.case_record_id,
                    "agent_role": self.role,
                    "display_name": self.display_name,
                    "status": result.status,
                    "input_preview": _preview(ctx.snapshot()),
                    "output_preview": _preview(result.output),
                    "latency_ms": result.latency_ms,
                    "token_usage": result.token_usage,
                    "error_msg": result.error_msg[:500] if result.error_msg else "",
                    "started_at": time.time(),
                    # Sprint A: resumability + trace tree
                    "tick": result.tick or ctx.current_tick,
                    "parent_run_id": ctx.parent_run_id or "",
                    "boundary_marker": (
                        "compact_boundary" if result.status == "ok" else ""
                    ),
                    "is_concurrency_safe": self.is_concurrency_safe,
                    "is_destructive": self.is_destructive,
                    "agent_risk_tier": self.risk_tier,
                },
            )
        except Exception:
            # Never let audit logging kill the run
            return None


def _preview(obj: Any, max_len: int = 800) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."
