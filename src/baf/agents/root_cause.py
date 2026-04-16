"""Root Cause Agent — analyzes logs + monitoring to find why.

Tool calls are mocked for the MVP (so the demo runs offline). The agent
receives simulated log/metric data and reasons through it.
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent, RunContext


def mock_read_logs(service: str, since_minutes: int = 15) -> str:
    # Deterministic fake logs — the Orchestrator can override with real ones later.
    return (
        f"[mock logs for {service}, last {since_minutes}min]\n"
        "2026-04-16 10:28:12 ERROR HikariPool - Connection is not available, request timed out after 30000ms.\n"
        "2026-04-16 10:28:15 WARN  com.order.db - active=200, idle=0, pending=45\n"
        "2026-04-16 10:28:27 ERROR OrderService - java.sql.SQLException: Unable to acquire JDBC Connection\n"
        "2026-04-16 10:29:02 ERROR HikariPool - Connection is not available... (repeated 342 times)\n"
        "2026-04-16 10:30:01 WARN  LoadBalancer - upstream order-service 503, retry in 5s\n"
    )


def mock_query_monitoring(service: str) -> dict[str, Any]:
    return {
        "cpu": "95%+",
        "rt_p99_ms": 3120,
        "qps": 820,
        "db_connections_active": 200,
        "db_connections_max": 200,
        "db_connections_pending": 45,
        "thread_pool_saturation": "0.98",
    }


class RootCauseAgent(BaseAgent):
    role = "root_cause"
    display_name = "Root Cause Agent"
    temperature = 0.15
    json_mode = True
    system_prompt = """你是 Root Cause Agent —— 根因分析专家。
拿到故障现象、日志片段、监控指标后，推导最可能的根因。

严格 JSON：
{
  "root_cause": "<一句话>",
  "evidence": ["日志/指标证据1", "证据2"],
  "confidence": 0.85,
  "related_components": ["组件A", "组件B"]
}
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        # In a real system: call storage / APM / log search. MVP: mocked.
        service = ctx.findings.get("target_service", "order-service")
        logs = mock_read_logs(service)
        metrics = mock_query_monitoring(service)

        user = (
            f"【故障描述】{ctx.description}\n"
            f"【监控指标】{metrics}\n"
            f"【日志片段】\n{logs}\n\n"
            "请给出根因和证据链。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        ctx.findings["root_cause"] = data.get("root_cause", "")
        ctx.findings["rc_evidence"] = data.get("evidence", [])
        ctx.findings["rc_confidence"] = data.get("confidence", 0.0)
        return {
            "root_cause": data.get("root_cause", ""),
            "evidence": data.get("evidence", []),
            "confidence": float(data.get("confidence", 0.0)),
            "related_components": data.get("related_components", []),
            "tools_called": ["read_logs", "query_monitoring"],
        }
