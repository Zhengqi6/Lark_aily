"""Verification Agent — independently judges if the task is done.

Runs *after* the fix is applied (in MVP we assume it succeeded). It
compares the claimed outcome against acceptance_criteria of the used
skills and produces a pass/fail verdict + issues + improvement suggestions.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent, RunContext


class VerificationAgent(BaseAgent):
    role = "verification"
    display_name = "Verification Agent"
    temperature = 0.1
    json_mode = True
    is_concurrency_safe = True
    is_destructive = False
    risk_tier = "low"
    search_hint = "independently verify task acceptance criteria"
    system_prompt = """你是 Verification Agent —— 独立的结果验证器。
严格按照【验收标准】判断任务是否完成，不要被过程论述带偏。

严格 JSON：
{
  "passed": true,
  "issues": ["..."],
  "suggestions": ["..."],
  "score": 0.9,
  "summary": "一句话"
}
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        criteria_lines = []
        for s in ctx.skills:
            ac = s.get("acceptance_criteria")
            if ac:
                criteria_lines.append(f"- [{s['skill_id']} {s.get('skill_name','')}] {ac}")
        criteria = "\n".join(criteria_lines) or "（无显式标准，依据任务描述判断）"

        deliverables = {
            "severity": ctx.severity,
            "root_cause": ctx.findings.get("root_cause"),
            "rc_evidence": ctx.findings.get("rc_evidence"),
            "fix_steps": ctx.findings.get("fix_steps"),
            "fix_rollback": ctx.findings.get("fix_rollback"),
        }
        user = (
            f"【任务描述】{ctx.description}\n\n"
            f"【验收标准】\n{criteria}\n\n"
            f"【实际交付】{deliverables}\n\n"
            "请给出验证结论。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        ctx.findings["verification"] = data
        return data
