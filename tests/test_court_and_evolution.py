"""Sprint B+C tests — Court agent fast path, Evolution distillation,
ApprovalRegistry round-trip, and AflowMCTS scoring."""
from __future__ import annotations

import asyncio
import json

import pytest

from baf.agents.base import RunContext
from baf.agents.court import CourtAgent
from baf.evolution.aflow_mcts import AflowMCTS
from baf.evolution.distill import Evolution
from baf.hooks.approvals import ApprovalRegistry
from baf.llm.client import LLMResponse
from baf.skills.hub import SkillHub
from baf.storage.backend import TableName
from baf.storage.mock_backend import MockBackend


class _StubLLM:
    """Returns canned JSON for whichever persona/role is calling."""

    default_model = "stub"

    def __init__(self, mode: str = "pass"):
        self.mode = mode  # 'pass' | 'fail' | 'split'

    def chat(self, messages, *, model=None, temperature=0.3, json_mode=False,
             max_tokens=None, timeout=60, retries=2):
        sys = next((m["content"] for m in messages if m["role"] == "system"), "")
        # Court personas
        if "结果验证官" in sys or "质疑者" in sys or "SRE 资深专家" in sys or "数据科学家" in sys:
            if self.mode == "pass":
                payload = {"passed": True, "score": 0.9, "issues": [], "rationale": "ok"}
            elif self.mode == "fail":
                payload = {"passed": False, "score": 0.4, "issues": ["risky"],
                           "rationale": "回滚不明"}
            else:
                # split: 1 fail among 3
                if "质疑者" in sys:
                    payload = {"passed": False, "score": 0.45, "issues": ["edge"],
                               "rationale": "存在边缘情况"}
                else:
                    payload = {"passed": True, "score": 0.85, "issues": [], "rationale": "ok"}
            return LLMResponse(content=json.dumps(payload, ensure_ascii=False),
                               model="stub")
        # Default verifier path (fast verifier on low risk)
        return LLMResponse(
            content=json.dumps({"passed": True, "score": 0.92,
                                "summary": "fast verifier ok",
                                "issues": [], "suggestions": []}),
            model="stub",
        )


def _make_ctx(risk_tier: str = "high") -> RunContext:
    return RunContext(
        case_id="C1", case_record_id="r1",
        description="Redis 主节点宕机",
        scene_type="故障处置", severity="P1",
        risk_tier=risk_tier,
        findings={
            "root_cause": "redis 主节点心跳丢失",
            "fix_steps": [{"order": 1, "action": "切换到从节点"}],
            "fix_rollback": "保留旧主，5 分钟可回滚",
        },
    )


def test_court_high_risk_majority_pass(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    court = CourtAgent(_StubLLM("pass"), sb)
    verdict = asyncio.run(court.adjudicate(_make_ctx("high")))
    assert verdict.passed is True
    assert len(verdict.votes) == 3
    assert verdict.score >= 0.8


def test_court_high_risk_split_majority_pass(tmp_path):
    """One skeptic dissents but majority (2/3) still passes."""
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    court = CourtAgent(_StubLLM("split"), sb)
    verdict = asyncio.run(court.adjudicate(_make_ctx("high")))
    assert verdict.passed is True
    assert sum(v.passed for v in verdict.votes) == 2


def test_court_low_risk_uses_fast_path(tmp_path):
    """Low-risk should NOT spawn 3 personas — single verifier only."""
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    court = CourtAgent(_StubLLM("pass"), sb)
    verdict = asyncio.run(court.adjudicate(_make_ctx("low")))
    assert verdict.passed is True
    assert len(verdict.votes) == 1   # fast path = single verifier


def test_evolution_distill_passed(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    # add a fake AgentRuns row that mentions tools
    sb.create_record(TableName.AGENT_RUNS, {
        "case_id": "C1", "agent_role": "root_cause",
        "output_preview": '{"tools_called":["read_logs","query_monitoring"]}',
    })
    sb.create_record(TableName.AGENT_BLUEPRINTS, {
        "blueprint_id": "BP_X", "scene_type": "故障处置",
        "team_composition": [], "success_rate": 0.5, "usage_count": 1,
    })
    bp_id = sb.list_records(TableName.AGENT_BLUEPRINTS)[0]["_id"]

    ctx = _make_ctx("high")
    ctx.blackboard["blueprint_record_id"] = bp_id
    ctx.findings["rc_confidence"] = 0.8
    evo = Evolution(sb)
    res = evo.distill(ctx, passed=True)
    assert res.sop_id is not None
    assert len(sb.list_records(TableName.MEMORY_SOP)) == 1
    # blueprint EWMA bumped
    bp = sb.get_record(TableName.AGENT_BLUEPRINTS, bp_id)
    assert float(bp["success_rate"]) > 0.5


def test_approval_registry_round_trip(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    reg = ApprovalRegistry(sb)
    card = reg.request("C1", "run_1", {"action": "restart"})
    assert sb.list_records(TableName.PENDING_APPROVALS)[0]["status"] == "pending"

    reg.auto_approve(card)
    row = reg.get(card)
    assert row["status"] == "approved"

    ev = reg.wait_for(card, max_wait=1)
    assert ev.status == "approved"


def test_aflow_mcts_picks_best(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    # historical blueprint with high success_rate
    sb.create_record(TableName.AGENT_BLUEPRINTS, {
        "blueprint_id": "BP_HIST", "scene_type": "故障处置",
        "team_composition": [
            {"role": "incident_commander"}, {"role": "root_cause"},
            {"role": "fix"}, {"role": "verification"},
        ],
        "success_rate": 0.95, "usage_count": 5,
    })
    mcts = AflowMCTS(sb, n_samples=3)

    def gen(seed: int):
        if seed == 0:
            return [{"role": "incident_commander"}, {"role": "root_cause"},
                    {"role": "fix"}, {"role": "verification"}]
        # weak alternatives
        return [{"role": f"role_{seed}_a"}, {"role": f"role_{seed}_b"}]

    winner = mcts.search("故障处置", gen, n_samples=3)
    assert winner.team[0]["role"] == "incident_commander"
    assert winner.score > 0


def test_get_max_tick(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    assert sb.get_max_tick("C1") == 0
    sb.create_record(TableName.AGENT_RUNS, {"case_id": "C1", "tick": 3})
    sb.create_record(TableName.AGENT_RUNS, {"case_id": "C1", "tick": 5})
    sb.create_record(TableName.AGENT_RUNS, {"case_id": "C2", "tick": 9})
    assert sb.get_max_tick("C1") == 5
    assert sb.get_max_tick("C2") == 9


def test_skill_hub_retrieve_filters_by_scene(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    sb.create_record(TableName.SKILL_CATALOG, {
        "skill_id": "S1", "skill_name": "告警分级",
        "applicable_scenes": ["故障处置"], "search_hint": "incident grading",
        "description": "P0-P3 grading", "risk_level": "低",
    })
    sb.create_record(TableName.SKILL_CATALOG, {
        "skill_id": "S2", "skill_name": "客户画像",
        "applicable_scenes": ["销售推进"], "search_hint": "customer profile",
        "description": "client profile", "risk_level": "低",
    })
    hub = SkillHub(sb)
    skills = hub.retrieve("incident grading", scene="故障处置", top_k=5)
    assert any(s.id == "S1" for s in skills)
    assert all(s.id != "S2" for s in skills)


def test_skill_hub_invoke_with_mock_mcp(tmp_path):
    sb = MockBackend(root=tmp_path); sb.ensure_tables()
    sb.create_record(TableName.SKILL_CATALOG, {
        "skill_id": "S1", "skill_name": "日志拉取",
        "applicable_scenes": ["故障处置"], "description": "logs",
        "required_tools": ["read_logs"], "risk_level": "低",
    })
    hub = SkillHub(sb)
    out = hub.invoke("S1", {"service": "order"})
    assert out["tool"] == "read_logs"
    assert out["result"]["lines"] == 5
    assert out["policy_decision"] == "allow"
