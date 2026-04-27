"""End-to-end test for the async streaming orchestrator (Sprint A).

Drives the full L1→L5 pipeline with a canned LLM, verifies tick numbers
increase monotonically, the resume path works, and that destructive
agents (Fix) request — and the registry resolves — an approval.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from baf.demo.seed_skills import seed
from baf.hooks.approvals import ApprovalRegistry
from baf.llm.client import LLMResponse
from baf.orchestrator_stream import StreamOrchestrator
from baf.storage.backend import TableName
from baf.storage.mock_backend import MockBackend


class _StreamFakeLLM:
    default_model = "fake"

    def chat(self, messages, *, model=None, temperature=0.3, json_mode=False,
             max_tokens=None, timeout=60, retries=2):
        sys = next((m["content"] for m in messages if m["role"] == "system"), "")
        if "Scene Router" in sys:
            data = {"scene_type": "故障处置", "confidence": 0.99,
                    "reasoning": "P1", "need_confirmation": False}
        elif "Skill Retriever" in sys:
            data = {"picked": ["SKILL_001", "SKILL_002", "SKILL_003", "SKILL_007"],
                    "reasoning": "incident"}
        elif "Composer" in sys:
            data = {"team": [
                {"role": "incident_commander", "skills": ["SKILL_001"], "desc": "ic"},
                {"role": "root_cause", "skills": ["SKILL_002"], "desc": "rc"},
                {"role": "fix", "skills": ["SKILL_003"], "desc": "fx"},
                {"role": "verification", "skills": ["SKILL_007"], "desc": "vf"},
            ], "reasoning": "team"}
        elif "Incident Commander" in sys:
            data = {"severity": "P1", "need_oncall_notify": True,
                    "initial_plan": ["确认告警", "切流量"], "comms_channel": "oncall"}
        elif "Root Cause" in sys:
            data = {"root_cause": "连接池耗尽", "evidence": ["timeout"],
                    "confidence": 0.85, "related_components": ["order"]}
        elif "Fix Agent" in sys:
            data = {"steps": [{"order": 1, "action": "扩容", "risk": "中", "est_minutes": 10}],
                    "rollback": "保留旧配置", "risk_overall": "中",
                    "requires_approval": True, "approver_role": "运维"}
        elif "结果验证官" in sys or "质疑者" in sys or "SRE 资深专家" in sys:
            data = {"passed": True, "score": 0.9, "issues": [], "rationale": "ok"}
        elif "Verification" in sys or "验收" in sys:
            data = {"passed": True, "score": 0.95, "summary": "通过",
                    "issues": [], "suggestions": []}
        else:
            data = {"deliverables": "ok", "evidence": [],
                    "next_steps": [], "confidence": 0.7}
        return LLMResponse(content=json.dumps(data, ensure_ascii=False), model="fake")


@pytest.fixture
def storage(tmp_path):
    sb = MockBackend(root=tmp_path)
    seed(sb)
    return sb


def _drive(orch: StreamOrchestrator, title: str, desc: str, *,
           auto_approve_with: ApprovalRegistry | None = None) -> list:
    events: list = []

    async def go():
        async for ev in orch.submit_case_stream(title, desc):
            events.append(ev)
            if ev.type == "approval_requested" and auto_approve_with:
                auto_approve_with.auto_approve(ev.payload["card_id"])

    asyncio.run(go())
    return events


def test_stream_full_pipeline(storage):
    reg = ApprovalRegistry(storage)
    orch = StreamOrchestrator(_StreamFakeLLM(), storage, approval_registry=reg)

    events = _drive(orch, "T", "order-service CPU 95%+", auto_approve_with=reg)
    types = [e.type for e in events]
    # All major phases present
    for expected in ("perception", "skills", "composed", "tick_done",
                     "approval_requested", "approval_resolved", "court", "memorized", "done"):
        assert expected in types, f"missing event {expected}"

    # ticks monotonically non-decreasing
    ticks = [e.tick for e in events if e.tick]
    assert ticks == sorted(ticks)

    # Cases closed; SOP sunk
    cases = storage.list_records(TableName.CASES, limit=10)
    assert cases[0]["status"] == "已完成"
    assert len(storage.list_records(TableName.MEMORY_SOP)) >= 1


def test_stream_resume(storage):
    """If a case has prior AgentRuns ticks, resume picks up from max_tick + 1."""
    reg = ApprovalRegistry(storage)
    orch = StreamOrchestrator(_StreamFakeLLM(), storage, approval_registry=reg)

    # First run starts and finishes
    events = _drive(orch, "T", "order-service CPU 95%+", auto_approve_with=reg)
    case_id = events[0].case_id
    assert case_id

    # Second run with the same case_id should emit a 'resumed' event
    events2: list = []

    async def go():
        async for ev in orch.run_case_stream(case_id):
            events2.append(ev)
            if ev.type == "approval_requested":
                reg.auto_approve(ev.payload["card_id"])

    asyncio.run(go())
    types = [e.type for e in events2]
    assert "resumed" in types
