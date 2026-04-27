"""L5 Evolution — distill successful runs into reusable assets.

Three outputs (DMSAS_Design.md §三.亮点 4):
  1. Memory/SOP — narrative + key decisions for future retrieval
  2. New auto-distilled skills — tool combos that recurred in trace
  3. Blueprint EWMA update — reinforce branches that worked

We only consider trace segments preceded by `boundary_marker=compact_boundary`
(written by BaseAgent.run on success). This is the trick borrowed from
Claude Code's `compact_boundary` — it prevents failed mid-run noise from
poisoning the SOP library.
"""
from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from ..agents.base import RunContext
from ..storage.backend import StorageBackend, TableName


_EWMA_ALPHA = 0.3


@dataclass
class DistillResult:
    sop_id: str | None = None
    new_skills: list[str] = None  # type: ignore[assignment]
    blueprint_updated: bool = False

    def __post_init__(self) -> None:
        if self.new_skills is None:
            self.new_skills = []


class Evolution:
    def __init__(self, storage: StorageBackend):
        self.storage = storage

    # ---- public ---------------------------------------------------
    def distill(self, ctx: RunContext, *, passed: bool) -> DistillResult:
        if not passed:
            # Failure path: only update blueprint EWMA, don't pollute SOP/skills.
            self._ewma_update(ctx, success=False)
            return DistillResult(blueprint_updated=True)

        sop_id = self._sink_sop(ctx)
        new_skills = self._distill_skills(ctx)
        self._ewma_update(ctx, success=True)
        return DistillResult(
            sop_id=sop_id, new_skills=new_skills, blueprint_updated=True
        )

    # ---- 1) SOP ---------------------------------------------------
    def _sink_sop(self, ctx: RunContext) -> str | None:
        try:
            steps = ctx.findings.get("fix_steps") or self._derive_steps(ctx)
            sop_id = f"SOP_{ctx.scene_type}_{ctx.case_id[:8]}"
            narrative = self._summarize(ctx)
            decisions = self._extract_decisions(ctx)
            self.storage.create_record(
                TableName.MEMORY_SOP,
                {
                    "sop_id": sop_id,
                    "scene_type": ctx.scene_type,
                    "title": (ctx.findings.get("root_cause") or "")[:60]
                             or f"{ctx.scene_type} SOP",
                    "trigger_condition": ctx.description[:200],
                    "steps": steps,
                    "source_case_id": ctx.case_id,
                    "confidence": ctx.findings.get("rc_confidence", 0.0),
                    "narrative": narrative,
                    "key_decisions": decisions,
                },
            )
            return sop_id
        except Exception:
            return None

    def _summarize(self, ctx: RunContext) -> str:
        rc = ctx.findings.get("root_cause") or ""
        verdict = ctx.findings.get("verification") or {}
        summary = verdict.get("summary") or ""
        return (
            f"场景={ctx.scene_type}；根因={rc[:60]}；"
            f"裁定={summary[:80]}"
        )

    def _extract_decisions(self, ctx: RunContext) -> list[str]:
        out: list[str] = []
        if ctx.severity:
            out.append(f"sev={ctx.severity}")
        rc = ctx.findings.get("root_cause")
        if rc:
            out.append(f"root_cause={str(rc)[:60]}")
        steps = ctx.findings.get("fix_steps") or []
        if steps:
            out.append(f"fix_step_count={len(steps)}")
        return out

    def _derive_steps(self, ctx: RunContext) -> list[dict[str, Any]]:
        # Fallback when no explicit fix_steps were produced (non-incident scenes).
        out: list[dict[str, Any]] = []
        for k, v in ctx.findings.items():
            if isinstance(v, dict) and "deliverables" in v:
                out.append({"role": k, "deliverable": str(v["deliverables"])[:200]})
        return out[:8]

    # ---- 2) auto-distill skills -----------------------------------
    def _distill_skills(self, ctx: RunContext) -> list[str]:
        """Mine the trace for recurring tool combos and register them."""
        runs = self.storage.list_records(
            TableName.AGENT_RUNS, where={"case_id": ctx.case_id}, limit=200
        )
        # naive heuristic: any agent with ≥2 distinct tools called → candidate skill
        groups: dict[str, set[str]] = {}
        for r in runs:
            preview = str(r.get("output_preview") or "")
            tools = self._guess_tools(preview)
            if not tools:
                continue
            groups.setdefault(r.get("agent_role") or "?", set()).update(tools)

        new_ids: list[str] = []
        for role, tools in groups.items():
            if len(tools) < 2:
                continue
            cand_id = f"SKILL_AUTO_{role[:8]}_{ctx.case_id[:6]}"
            if self._is_duplicate(cand_id, role, tools):
                continue
            self.storage.create_record(
                TableName.SKILL_CATALOG,
                {
                    "skill_id": cand_id,
                    "skill_name": f"{role} 组合技能",
                    "applicable_scenes": [ctx.scene_type] if ctx.scene_type else [],
                    "permission_level": "普通",
                    "risk_level": "低",
                    "input_requirements": "继承 agent 输入",
                    "output_format": "见原 agent 输出格式",
                    "required_tools": sorted(tools),
                    "acceptance_criteria": "重现原 agent 在该 case 上的成功路径",
                    "description": f"从成功 case {ctx.case_id} 自动蒸馏",
                    "auto_distilled": True,
                    "source_case_id": ctx.case_id,
                    "search_hint": f"distilled from {role}",
                },
            )
            new_ids.append(cand_id)
        return new_ids

    @staticmethod
    def _guess_tools(preview: str) -> set[str]:
        out: set[str] = set()
        for tool in ("read_logs", "query_monitoring", "query_metrics",
                     "notify_oncall", "send_feishu_card",
                     "get_system_architecture"):
            if tool in preview:
                out.add(tool)
        return out

    def _is_duplicate(self, cand_id: str, role: str, tools: set[str]) -> bool:
        existing = self.storage.list_records(TableName.SKILL_CATALOG, limit=2000)
        for s in existing:
            if s.get("skill_id") == cand_id:
                return True
            t = s.get("required_tools") or []
            if isinstance(t, list) and set(t) == tools and role in (s.get("description") or ""):
                return True
        return False

    # ---- 3) blueprint EWMA ----------------------------------------
    def _ewma_update(self, ctx: RunContext, *, success: bool) -> None:
        bp_record_id = ctx.blackboard.get("blueprint_record_id")
        if not bp_record_id:
            return
        try:
            bp = self.storage.get_record(TableName.AGENT_BLUEPRINTS, bp_record_id)
            if not bp:
                return
            prev = float(bp.get("success_rate") or 0.0)
            sample = 1.0 if success else 0.0
            new_rate = round(_EWMA_ALPHA * sample + (1 - _EWMA_ALPHA) * prev, 3)
            self.storage.update_record(
                TableName.AGENT_BLUEPRINTS,
                bp_record_id,
                {"success_rate": new_rate, "last_used_at": time.time()},
            )
        except Exception:
            pass
