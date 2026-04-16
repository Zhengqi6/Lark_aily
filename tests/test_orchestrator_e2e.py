"""End-to-end orchestrator test with a canned LLM (no API calls).

We replay pre-scripted JSON for each agent so the full pipeline runs offline
and deterministically. This guards against regressions in:
  - role aliasing (Composer-invented roles → GenericAgent)
  - blueprint success_rate updates after a case closes
  - SOP sinking on passed cases
  - Agent Runs audit log population
"""
from __future__ import annotations

import json
from typing import Any

import pytest

from baf.agents.base import RunContext  # noqa: F401
from baf.demo.seed_skills import seed
from baf.llm.client import LLMResponse
from baf.orchestrator import Orchestrator
from baf.storage.backend import TableName
from baf.storage.mock_backend import MockBackend


class FakeLLM:
    """Minimal stand-in for LLMClient that routes prompts → canned JSON by keyword."""

    default_model = "fake-model"

    def chat(
        self,
        messages: list[dict],
        *,
        model: str | None = None,
        temperature: float = 0.3,
        json_mode: bool = False,
        max_tokens: int | None = None,
        timeout: float = 60.0,
        retries: int = 2,
    ) -> LLMResponse:
        sys_prompt = next((m["content"] for m in messages if m["role"] == "system"), "")
        user_prompt = next((m["content"] for m in messages if m["role"] == "user"), "")

        def resp(obj: Any) -> LLMResponse:
            return LLMResponse(
                content=json.dumps(obj, ensure_ascii=False),
                model="fake-model",
                prompt_tokens=10,
                completion_tokens=20,
                total_tokens=30,
                latency_ms=1,
            )

        if "Scene Router" in sys_prompt:
            return resp({
                "scene_type": "故障处置",
                "confidence": 0.95,
                "reasoning": "测试环境：强制返回故障处置",
                "need_confirmation": False,
            })
        if "Skill Retriever" in sys_prompt:
            return resp({
                "picked": ["SKILL_001", "SKILL_002", "SKILL_003", "SKILL_007"],
                "reasoning": "incident standard four",
            })
        if "Composer" in sys_prompt:
            return resp({
                "team": [
                    {"role": "incident_commander", "skills": ["SKILL_001"], "desc": "ic"},
                    {"role": "root_cause", "skills": ["SKILL_002"], "desc": "rc"},
                    {"role": "fix", "skills": ["SKILL_003"], "desc": "fx"},
                    {"role": "verification", "skills": ["SKILL_007"], "desc": "vf"},
                ],
                "reasoning": "classic incident team",
            })
        if "Incident Commander" in sys_prompt:
            return resp({
                "severity": "P1",
                "need_oncall_notify": True,
                "plan": "分级→调查→修复→验证",
                "key_risks": ["级联扩散"],
            })
        if "Root Cause" in sys_prompt:
            return resp({
                "root_cause": "数据库连接池耗尽",
                "evidence": ["HikariPool timeout", "active=200/200"],
                "confidence": 0.88,
                "related_components": ["order-service", "MySQL"],
            })
        if "Fix Agent" in sys_prompt:
            return resp({
                "steps": ["扩容连接池", "重启实例"],
                "rollback": "保留旧配置备份",
                "risk_overall": "中",
                "estimated_minutes": 15,
            })
        if "Verification" in sys_prompt or "验收" in sys_prompt:
            return resp({
                "passed": True,
                "score": 0.95,
                "summary": "所有验收项通过",
                "issues": [],
            })
        # GenericAgent catch-all
        return resp({
            "deliverables": "generic output",
            "evidence": [],
            "next_steps": [],
            "confidence": 0.7,
        })


@pytest.fixture()
def storage(tmp_path):
    sb = MockBackend(root=tmp_path)
    seed(sb)
    return sb


def test_full_incident_pipeline(storage):
    orch = Orchestrator(FakeLLM(), storage)
    result = orch.submit_case(
        "订单服务 CPU 告警",
        "order-service CPU 95%+，大量 connection timeout",
    )

    assert result.passed is True
    assert result.scene_type == "故障处置"
    assert result.severity == "P1"

    # Case closed in Cases table
    cases = storage.list_records(TableName.CASES, where={"task_id": result.case_id})
    assert cases and cases[0]["status"] == "已完成"
    assert cases[0].get("sop_ref")

    # At least 7 agent runs written (router, retriever, composer, IC, RC, FX, VF)
    runs = storage.list_records(
        TableName.AGENT_RUNS, where={"case_id": result.case_id}, limit=50
    )
    roles = [r.get("agent_role") for r in runs]
    for expected in ["scene_router", "skill_retriever", "composer",
                     "incident_commander", "root_cause", "fix", "verification"]:
        assert expected in roles, f"missing agent run: {expected}"

    # SOP was sunk
    sops = storage.list_records(
        TableName.MEMORY_SOP, where={"source_case_id": result.case_id}
    )
    assert len(sops) == 1

    # Blueprint success_rate was nudged upward (starts at 0.92, sample=1, EWMA α=0.3 → 0.944)
    bps = storage.list_records(
        TableName.AGENT_BLUEPRINTS, where={"blueprint_id": "BP_INCIDENT_V1"}
    )
    assert bps
    assert float(bps[0]["success_rate"]) > 0.92


def test_blueprint_decays_on_failure(storage):
    """Verification fails → blueprint's success_rate goes down."""
    class FailingLLM(FakeLLM):
        def chat(self, messages, **kw):
            # flip verification result to failed
            resp = super().chat(messages, **kw)
            sys = next((m["content"] for m in messages if m["role"] == "system"), "")
            if "Verification" in sys or "验收" in sys:
                import json as _j
                return type(resp)(
                    content=_j.dumps({
                        "passed": False,
                        "score": 0.4,
                        "summary": "连接池未恢复",
                        "issues": ["pending 仍 > 30"],
                    }, ensure_ascii=False),
                    model=resp.model,
                    prompt_tokens=resp.prompt_tokens,
                    completion_tokens=resp.completion_tokens,
                    total_tokens=resp.total_tokens,
                    latency_ms=resp.latency_ms,
                )
            return resp

    orch = Orchestrator(FailingLLM(), storage)
    result = orch.submit_case("T", "incident payload")
    assert result.passed is False

    bps = storage.list_records(
        TableName.AGENT_BLUEPRINTS, where={"blueprint_id": "BP_INCIDENT_V1"}
    )
    # baseline 0.92, sample=0, α=0.3 → 0.644
    assert float(bps[0]["success_rate"]) < 0.92
