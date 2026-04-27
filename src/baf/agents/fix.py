"""Fix Agent — proposes repair plan with rollback + risk assessment.

Key operations (e.g. restart, scale-up) would require 飞书卡片审批 in
production. MVP simulates the approval by a console yes/no prompt or
auto-approve flag.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent, RunContext


class FixAgent(BaseAgent):
    role = "fix"
    display_name = "Fix Agent"
    temperature = 0.2
    json_mode = True
    # Fix runs commands that change live state — destructive, must go through approval.
    is_concurrency_safe = False
    is_destructive = True
    risk_tier = "high"
    search_hint = "design repair plan with rollback for incident"
    system_prompt = """你是 Fix Agent —— 故障修复方案设计师。
拿到根因后，给出具体修复方案。

严格 JSON：
{
  "steps":[{"order":1,"action":"...","risk":"低|中|高","est_minutes":5}],
  "rollback": "如果出问题怎么回滚（1-2 句）",
  "risk_overall": "低|中|高",
  "requires_approval": true,
  "approver_role": "运维负责人",
  "reasoning": "为什么选这个方案"
}
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        root_cause = ctx.findings.get("root_cause", "未知")
        evidence = ctx.findings.get("rc_evidence", [])
        user = (
            f"【根因】{root_cause}\n"
            f"【证据】{evidence}\n"
            f"【故障描述】{ctx.description}\n\n"
            "请给出修复步骤、风险和回滚方案。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        ctx.findings["fix_steps"] = data.get("steps", [])
        ctx.findings["fix_rollback"] = data.get("rollback", "")
        ctx.findings["fix_risk"] = data.get("risk_overall", "中")
        return data
