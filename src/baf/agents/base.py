"""Agent base class.

Every agent inherits from BaseAgent. A run() call does three things:
  1) Construct prompt from system_prompt + context
  2) Call LLM (possibly multi-turn with tools)
  3) Persist an entry in AgentRuns — this is what makes the "virtual
     organization" visible inside the Bitable.
"""
from __future__ import annotations

import json
import time
import traceback
from dataclasses import dataclass, field
from typing import Any

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
    skills: list[dict] = field(default_factory=list)  # retrieved skill records
    team: list[dict] = field(default_factory=list)    # composed agent roles
    findings: dict[str, Any] = field(default_factory=dict)  # shared scratchpad
    blackboard: dict[str, Any] = field(default_factory=dict)

    def snapshot(self) -> dict[str, Any]:
        return {
            "case_id": self.case_id,
            "scene_type": self.scene_type,
            "severity": self.severity,
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


class BaseAgent:
    role: str = "base"
    display_name: str = "Base Agent"
    system_prompt: str = ""
    temperature: float = 0.2
    json_mode: bool = True
    model: str | None = None    # None → use client default

    def __init__(self, llm: LLMClient, storage: StorageBackend):
        self.llm = llm
        self.storage = storage

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
            )
        except Exception as e:
            result = AgentResult(
                role=self.role,
                status="error",
                output={},
                latency_ms=int((time.time() - t0) * 1000),
                error_msg=f"{e}\n{traceback.format_exc(limit=3)}",
            )
        self._record_run(ctx, result)
        return result

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

    def _record_run(self, ctx: RunContext, result: AgentResult) -> None:
        """Write one row to AgentRuns so the Bitable shows the agent timeline."""
        try:
            self.storage.create_record(
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
                },
            )
        except Exception:
            # Never let audit logging kill the run
            pass


def _preview(obj: Any, max_len: int = 800) -> str:
    try:
        s = json.dumps(obj, ensure_ascii=False, default=str)
    except Exception:
        s = str(obj)
    return s if len(s) <= max_len else s[: max_len - 3] + "..."
