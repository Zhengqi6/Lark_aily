"""Court Agent — three-persona critic (Verifier / Skeptic / Domain Expert).

Replaces the single-Critic VerificationAgent for high-risk cases. Design
ref: DMSAS_Design.md §三.亮点 3 (MAR persona-diversity, ReliabilityBench).

The three personas independently score the case under different prompts /
temperatures, then a short "merge" step combines critiques. Majority pass
(≥2/3) is required to land.

Cost: ~3× tokens vs. the fast verifier — only invoked when
`ctx.risk_tier in {"high", "critical"}` to keep low-risk cases cheap.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

from .base import BaseAgent, RunContext
from .verification import VerificationAgent


@dataclass
class PersonaVote:
    persona: str
    passed: bool
    score: float
    issues: list[str] = field(default_factory=list)
    rationale: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "persona": self.persona,
            "passed": self.passed,
            "score": self.score,
            "issues": self.issues,
            "rationale": self.rationale,
        }


@dataclass
class Verdict:
    passed: bool
    score: float
    summary: str
    votes: list[PersonaVote] = field(default_factory=list)
    improvement: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "passed": self.passed,
            "score": round(self.score, 3),
            "summary": self.summary,
            "votes": [v.to_dict() for v in self.votes],
            "improvement": self.improvement,
        }


# Domain prompts get plugged in based on `ctx.scene_type`.
_DOMAIN_PROMPTS = {
    "故障处置":
        "你是 SRE 资深专家，重点检查：止血动作是否会引起二次故障；回滚条件是否明确；"
        "RC 证据链是否成环。",
    "销售推进":
        "你是 To-B 资深销售总监，重点检查：BANT 完整性；竞品对比是否有事实支撑；"
        "下一步动作是否可执行。",
    "招聘流程":
        "你是 HR Tech Lead，重点检查：JD/简历匹配判据；面试题分层；薪酬区间是否覆盖市场分位。",
    "采购审批":
        "你是采购合规官，重点检查：是否覆盖至少 3 家比价；资质证件是否核验；"
        "金额是否触发额外审批节点。",
    "运营分析":
        "你是数据科学家，重点检查：归因区分相关 vs 因果；置信度是否说明；"
        "结论是否落到可执行 next step。",
    "其他":
        "你是资深业务专家，重点检查任务是否真的被完成、关键风险是否覆盖。",
}


_PERSONA_CFG = {
    "verifier":      {"temperature": 0.1, "stance": "你是结果验证官，默认从严判定通过。"},
    "skeptic":       {"temperature": 0.7, "stance": "你是质疑者，默认从严挑反例与盲点。"},
    "domain_expert": {"temperature": 0.3, "stance": ""},  # filled by scene
}


_BASE_RUBRIC = """严格按以下 JSON 输出（不要任何多余内容）：
{
  "passed": true|false,
  "score": 0.0~1.0,
  "issues": ["最多 5 条具体问题，每条 ≤ 30 字"],
  "rationale": "≤ 80 字，写明你判定的关键依据"
}
"""


class CourtAgent(BaseAgent):
    """High-risk verification: 3 personas → vote → verdict."""

    role = "court"
    display_name = "Verification Court"
    json_mode = True
    is_concurrency_safe = True
    is_destructive = False
    risk_tier = "low"
    search_hint = "multi-persona critic for high risk cases"

    async def adjudicate(self, ctx: RunContext) -> Verdict:
        # Low risk → fast verifier (single agent, cheap).
        if ctx.risk_tier in {"low", "mid"}:
            return await self._fast_verify(ctx)

        votes = await asyncio.gather(
            *[self._persona_vote(name, ctx) for name in _PERSONA_CFG.keys()]
        )
        passed = sum(v.passed for v in votes) >= 2
        avg_score = sum(v.score for v in votes) / max(1, len(votes))
        summary = self._merge_summary(votes, passed)
        improvement = self._merge_critiques(votes) if not passed else ""
        verdict = Verdict(
            passed=passed,
            score=avg_score,
            summary=summary,
            votes=votes,
            improvement=improvement,
        )
        # piggy-back on standard run-recording so it shows up in AgentRuns
        ctx.findings["verification"] = verdict.to_dict()
        # also fire a single AgentRuns row for the Court itself
        try:
            self.storage  # noqa: B018  (just to ensure attribute access works)
        except Exception:
            pass
        return verdict

    # ---------- low-risk fast path -------------------------------
    async def _fast_verify(self, ctx: RunContext) -> Verdict:
        """Fall back to the single-Critic VerificationAgent."""
        verifier = VerificationAgent(self.llm, self.storage)
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, verifier.run, ctx)
        v = ctx.findings.get("verification") or {}
        return Verdict(
            passed=bool(v.get("passed")),
            score=float(v.get("score") or 0),
            summary=str(v.get("summary") or ""),
            votes=[
                PersonaVote(
                    persona="verifier",
                    passed=bool(v.get("passed")),
                    score=float(v.get("score") or 0),
                    issues=list(v.get("issues") or []),
                    rationale="fast-path single critic",
                )
            ],
            improvement="; ".join(v.get("suggestions") or [])[:300],
        )

    # ---------- persona vote -------------------------------------
    async def _persona_vote(self, persona: str, ctx: RunContext) -> PersonaVote:
        cfg = _PERSONA_CFG[persona]
        stance = cfg["stance"]
        if persona == "domain_expert":
            stance = _DOMAIN_PROMPTS.get(ctx.scene_type or "其他", _DOMAIN_PROMPTS["其他"])

        criteria_lines = []
        for s in ctx.skills:
            ac = s.get("acceptance_criteria")
            if ac:
                criteria_lines.append(f"- [{s['skill_id']}] {ac}")
        criteria = "\n".join(criteria_lines) or "（依任务描述自行判断）"

        deliverables = {
            "scene_type": ctx.scene_type,
            "severity": ctx.severity,
            "root_cause": ctx.findings.get("root_cause"),
            "fix_steps": ctx.findings.get("fix_steps"),
            "fix_rollback": ctx.findings.get("fix_rollback"),
            "fix_risk": ctx.findings.get("fix_risk"),
            "other": {k: v for k, v in ctx.findings.items()
                      if k not in {"root_cause", "fix_steps", "fix_rollback",
                                   "fix_risk", "rc_evidence", "rc_confidence",
                                   "verification", "initial_plan", "comms_channel"}},
        }
        sys = stance + "\n\n" + _BASE_RUBRIC
        usr = (
            f"【任务描述】{ctx.description}\n\n"
            f"【验收标准】\n{criteria}\n\n"
            f"【交付物】{deliverables}"
        )

        loop = asyncio.get_running_loop()

        def _call() -> dict[str, Any]:
            resp = self.llm.chat(
                [{"role": "system", "content": sys},
                 {"role": "user", "content": usr}],
                temperature=cfg["temperature"],
                json_mode=True,
            )
            try:
                return resp.as_json()
            except Exception:
                return {"passed": False, "score": 0.0,
                        "issues": ["LLM 返回非 JSON"], "rationale": resp.content[:120]}

        data = await loop.run_in_executor(None, _call)
        return PersonaVote(
            persona=persona,
            passed=bool(data.get("passed")),
            score=float(data.get("score") or 0.0),
            issues=[str(x) for x in (data.get("issues") or [])][:5],
            rationale=str(data.get("rationale") or "")[:200],
        )

    # ---------- merge -------------------------------------------
    def _merge_summary(self, votes: list[PersonaVote], passed: bool) -> str:
        verdict = "通过" if passed else "未通过"
        scores = ", ".join(f"{v.persona}={v.score:.2f}" for v in votes)
        return f"{verdict}（{scores}）"

    def _merge_critiques(self, votes: list[PersonaVote]) -> str:
        """Keep up to 5 distinct issues across all rejecting voters."""
        seen: set[str] = set()
        merged: list[str] = []
        for v in votes:
            if v.passed:
                continue
            for it in v.issues:
                if it in seen:
                    continue
                seen.add(it)
                merged.append(f"[{v.persona}] {it}")
                if len(merged) >= 5:
                    break
        return " | ".join(merged)
