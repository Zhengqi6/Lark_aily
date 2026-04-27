"""Field definitions for the 5 Bitable tables.

Bitable field-type numeric codes (see Feishu OpenAPI docs):
  1  文本   (single-line text)
  2  数字   (number)
  3  单选   (single select)
  4  多选   (multi select)
  5  日期   (datetime, unix-millis)
  7  复选框 (checkbox)
  11 人员   (person)
  13 电话
  15 超链接
  17 附件
  18 关联   (link to another table)
  19 查找引用
  20 公式
  22 地理位置
  23 群组
  1001 创建时间
  1002 修改时间
  1003 创建人
  1004 修改人
  1005 自动编号

For MVP we mostly use: 1 (text), 3 (single select), 4 (multi select),
5 (datetime), 2 (number).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from ..storage.backend import TableName


@dataclass
class FieldDef:
    name: str          # 字段名（中文友好）
    type: int          # Bitable 字段类型 code
    property: dict | None = None   # e.g. {"options":[{"name":"P0"},...]} for singleSelect

    def to_api(self) -> dict[str, Any]:
        d: dict[str, Any] = {"field_name": self.name, "type": self.type}
        if self.property:
            d["property"] = self.property
        return d


SCENE_OPTIONS = ["故障处置", "销售推进", "招聘流程", "采购审批", "运营分析", "其他"]
STATUS_OPTIONS = ["待识别", "识别中", "编组中", "执行中", "待审批", "已完成", "已失败"]
SEVERITY_OPTIONS = ["P0", "P1", "P2", "P3"]
RUN_STATUS_OPTIONS = ["ok", "error", "skipped"]
PERMISSION_OPTIONS = ["普通", "高级", "管理员"]
RISK_OPTIONS = ["低", "中", "高"]


# All table schemas — Bitable will happily auto-create any missing fields
# on the first write, but we declare them explicitly so the UX is clean.
SCHEMAS: dict[TableName, list[FieldDef]] = {
    TableName.CASES: [
        FieldDef("task_id", 1),
        FieldDef("title", 1),
        FieldDef("description", 1),
        FieldDef("scene_type", 3, {"options": [{"name": s} for s in SCENE_OPTIONS]}),
        FieldDef("severity", 3, {"options": [{"name": s} for s in SEVERITY_OPTIONS]}),
        FieldDef("status", 3, {"options": [{"name": s} for s in STATUS_OPTIONS]}),
        FieldDef("agent_team", 1),       # store as JSON string
        FieldDef("result_summary", 1),
        FieldDef("scene_confidence", 2),
        FieldDef("sop_ref", 1),
        FieldDef("created_at", 5),
        FieldDef("closed_at", 5),
    ],
    TableName.SKILL_CATALOG: [
        FieldDef("skill_id", 1),
        FieldDef("skill_name", 1),
        FieldDef("applicable_scenes", 4, {"options": [{"name": s} for s in SCENE_OPTIONS]}),
        FieldDef("permission_level", 3, {"options": [{"name": s} for s in PERMISSION_OPTIONS]}),
        FieldDef("risk_level", 3, {"options": [{"name": s} for s in RISK_OPTIONS]}),
        FieldDef("description", 1),
        FieldDef("input_requirements", 1),
        FieldDef("output_format", 1),
        FieldDef("required_tools", 1),
        FieldDef("acceptance_criteria", 1),
        FieldDef("call_count", 2),
        FieldDef("success_rate", 2),
    ],
    TableName.AGENT_BLUEPRINTS: [
        FieldDef("blueprint_id", 1),
        FieldDef("scene_type", 3, {"options": [{"name": s} for s in SCENE_OPTIONS]}),
        FieldDef("team_composition", 1),   # JSON-stringified
        FieldDef("success_rate", 2),
        FieldDef("usage_count", 2),
        FieldDef("desc", 1),
    ],
    TableName.AGENT_RUNS: [
        FieldDef("case_id", 1),
        FieldDef("case_ref", 1),
        FieldDef("agent_role", 1),
        FieldDef("display_name", 1),
        FieldDef("status", 3, {"options": [{"name": s} for s in RUN_STATUS_OPTIONS]}),
        FieldDef("input_preview", 1),
        FieldDef("output_preview", 1),
        FieldDef("latency_ms", 2),
        FieldDef("token_usage", 2),
        FieldDef("error_msg", 1),
        FieldDef("started_at", 5),
        # Sprint A: trace tree + resume checkpoints
        FieldDef("tick", 2),
        FieldDef("parent_run_id", 1),
        FieldDef("boundary_marker", 1),
        FieldDef("is_concurrency_safe", 7),
        FieldDef("is_destructive", 7),
        FieldDef("agent_risk_tier", 1),
    ],
    TableName.MEMORY_SOP: [
        FieldDef("sop_id", 1),
        FieldDef("scene_type", 3, {"options": [{"name": s} for s in SCENE_OPTIONS]}),
        FieldDef("title", 1),
        FieldDef("trigger_condition", 1),
        FieldDef("steps", 1),               # JSON-stringified
        FieldDef("source_case_id", 1),
        FieldDef("confidence", 2),
        FieldDef("narrative", 1),
        FieldDef("key_decisions", 1),
    ],
    TableName.PENDING_APPROVALS: [
        FieldDef("card_id", 1),
        FieldDef("case_id", 1),
        FieldDef("agent_run_id", 1),
        FieldDef(
            "status", 3,
            {"options": [{"name": s} for s in ["pending", "approved", "rejected", "timeout"]]},
        ),
        FieldDef("payload", 1),         # JSON-stringified
        FieldDef("decision_note", 1),
        FieldDef("requested_at", 5),
        FieldDef("expires_at", 5),
        FieldDef("decided_at", 5),
    ],
}


# Human-friendly table display names in Bitable.
TABLE_DISPLAY_NAMES: dict[TableName, str] = {
    TableName.CASES: "Cases · 任务",
    TableName.SKILL_CATALOG: "Skill Catalog · 技能库",
    TableName.AGENT_BLUEPRINTS: "Agent Blueprints · 模板",
    TableName.AGENT_RUNS: "Agent Runs · 执行记录",
    TableName.MEMORY_SOP: "Memory/SOP · 沉淀",
    TableName.PENDING_APPROVALS: "Pending Approvals · 待审批",
}
