"""Tests for MockBackend — pure storage, no LLM needed."""
from __future__ import annotations

from baf.storage.backend import TableName
from baf.storage.mock_backend import MockBackend


def test_create_get_update_delete(tmp_path):
    sb = MockBackend(root=tmp_path)
    sb.ensure_tables()

    rid = sb.create_record(
        TableName.CASES,
        {"task_id": "C1", "title": "hello", "scene_type": "故障处置"},
    )
    assert rid.startswith("rec_")

    rec = sb.get_record(TableName.CASES, rid)
    assert rec is not None
    assert rec["title"] == "hello"
    assert rec["scene_type"] == "故障处置"

    sb.update_record(TableName.CASES, rid, {"status": "已完成"})
    rec2 = sb.get_record(TableName.CASES, rid)
    assert rec2["status"] == "已完成"

    sb.delete_record(TableName.CASES, rid)
    assert sb.get_record(TableName.CASES, rid) is None


def test_list_with_where_scalar_match(tmp_path):
    sb = MockBackend(root=tmp_path)
    sb.ensure_tables()
    sb.create_record(TableName.CASES, {"task_id": "C1", "scene_type": "故障处置"})
    sb.create_record(TableName.CASES, {"task_id": "C2", "scene_type": "销售推进"})
    sb.create_record(TableName.CASES, {"task_id": "C3", "scene_type": "故障处置"})

    incident = sb.list_records(TableName.CASES, where={"scene_type": "故障处置"})
    assert len(incident) == 2
    assert {c["task_id"] for c in incident} == {"C1", "C3"}


def test_list_with_where_list_match(tmp_path):
    """If a stored field is a list (e.g. applicable_scenes), where=str matches against membership."""
    sb = MockBackend(root=tmp_path)
    sb.ensure_tables()
    sb.create_record(
        TableName.SKILL_CATALOG,
        {"skill_id": "S1", "applicable_scenes": ["故障处置", "采购审批"]},
    )
    sb.create_record(
        TableName.SKILL_CATALOG,
        {"skill_id": "S2", "applicable_scenes": ["销售推进"]},
    )
    matched = sb.list_records(
        TableName.SKILL_CATALOG, where={"applicable_scenes": "故障处置"}
    )
    assert [m["skill_id"] for m in matched] == ["S1"]


def test_seed_idempotent(tmp_path):
    """seed() can be called twice without duplicating rows."""
    from baf.demo.seed_skills import seed
    from baf.skills.builtin import BUILTIN_BLUEPRINTS, BUILTIN_SKILLS

    sb = MockBackend(root=tmp_path)
    s1, b1 = seed(sb)
    s2, b2 = seed(sb)
    assert s1 == len(BUILTIN_SKILLS)
    assert b1 == len(BUILTIN_BLUEPRINTS)
    assert s2 == 0 and b2 == 0   # second call is a no-op
    assert len(sb.list_records(TableName.SKILL_CATALOG)) == len(BUILTIN_SKILLS)
    assert len(sb.list_records(TableName.AGENT_BLUEPRINTS)) == len(BUILTIN_BLUEPRINTS)
