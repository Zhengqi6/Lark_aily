"""Incident Commander — judges severity and drives the incident flow."""
from __future__ import annotations

from typing import Any

from .base import BaseAgent, RunContext


class IncidentCommanderAgent(BaseAgent):
    role = "incident_commander"
    display_name = "Incident Commander"
    temperature = 0.1
    json_mode = True
    system_prompt = """你是 Incident Commander —— 一线故障指挥官。
给定故障描述，输出：
  - severity: P0 (全站不可用/严重资损) / P1 (核心链路严重降级) / P2 (非核心功能问题) / P3 (轻微)
  - need_oncall_notify: P0/P1 必须 true
  - initial_plan: 3-5 条初步行动（调查、联络、止血）
  - comms_channel: 告警群名称或值班组

严格 JSON：
{"severity":"P1","need_oncall_notify":true,"initial_plan":["...","..."],"comms_channel":"订单中台值班群","reasoning":"..."}
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        user = (
            f"【故障描述】{ctx.description}\n\n"
            "请判定 severity 并给出初始行动。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        sev = data.get("severity", "P2")
        if sev not in {"P0", "P1", "P2", "P3"}:
            sev = "P2"
        ctx.severity = sev
        ctx.findings["initial_plan"] = data.get("initial_plan", [])
        ctx.findings["comms_channel"] = data.get("comms_channel", "")
        return {
            "severity": sev,
            "need_oncall_notify": bool(data.get("need_oncall_notify", sev in {"P0", "P1"})),
            "initial_plan": data.get("initial_plan", []),
            "comms_channel": data.get("comms_channel", ""),
            "reasoning": str(data.get("reasoning", ""))[:200],
        }
