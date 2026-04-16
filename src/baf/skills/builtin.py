"""Built-in skill catalog + agent blueprints (seed data).

Focused on 故障处置 for the MVP; a few skills from other scenes are
included so Skill Retriever's cross-scene filtering has something to
filter out.
"""
from __future__ import annotations

BUILTIN_SKILLS: list[dict] = [
    # --- 故障处置 ---
    {
        "skill_id": "SKILL_001",
        "skill_name": "告警分级",
        "applicable_scenes": ["故障处置"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "告警描述、受影响系统、业务影响面",
        "output_format": "P0/P1/P2/P3 + 依据",
        "required_tools": ["get_system_architecture"],
        "acceptance_criteria": "必须给出明确等级及依据，依据需覆盖影响面、紧急度、频率",
        "description": "根据影响范围和紧急度把故障分到 P0-P3 四档",
    },
    {
        "skill_id": "SKILL_002",
        "skill_name": "根因分析",
        "applicable_scenes": ["故障处置"],
        "permission_level": "高级",
        "risk_level": "中",
        "input_requirements": "故障现象、日志片段、监控数据",
        "output_format": "根因 + 证据链 + 置信度",
        "required_tools": ["read_logs", "query_monitoring"],
        "acceptance_criteria": "根因明确、每一步推理都有日志/监控数据支撑",
        "description": "基于日志/监控/调用链推导故障根因",
    },
    {
        "skill_id": "SKILL_003",
        "skill_name": "修复方案设计",
        "applicable_scenes": ["故障处置"],
        "permission_level": "高级",
        "risk_level": "中",
        "input_requirements": "根因分析结果",
        "output_format": "步骤列表 + 回滚方案 + 风险评估",
        "required_tools": ["get_system_architecture"],
        "acceptance_criteria": "包含执行步骤、回滚方案、风险点、预计耗时",
        "description": "根据根因给出具体修复步骤并评估风险",
    },
    {
        "skill_id": "SKILL_004",
        "skill_name": "值班通知",
        "applicable_scenes": ["故障处置"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "故障信息、值班组",
        "output_format": "通知消息内容 + 接收人列表",
        "required_tools": ["notify_oncall"],
        "acceptance_criteria": "P0/P1 必须通知到人，包含故障标题、等级、处置链接",
        "description": "向值班人员发送故障通知",
    },
    {
        "skill_id": "SKILL_005",
        "skill_name": "审批卡片",
        "applicable_scenes": ["故障处置", "采购审批"],
        "permission_level": "高级",
        "risk_level": "中",
        "input_requirements": "待审批内容、审批人",
        "output_format": "卡片消息 + 审批状态",
        "required_tools": ["send_feishu_card"],
        "acceptance_criteria": "审批人明确、卡片内容完整、留有审批链接",
        "description": "把关键决策通过飞书卡片发给审批人",
    },
    {
        "skill_id": "SKILL_006",
        "skill_name": "故障复盘沉淀",
        "applicable_scenes": ["故障处置"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "故障全过程记录",
        "output_format": "SOP 文档 + 触发条件 + 步骤",
        "required_tools": [],
        "acceptance_criteria": "可复用为未来同类故障的处置模板",
        "description": "把一次成功处置转化为可复用 SOP",
    },
    {
        "skill_id": "SKILL_007",
        "skill_name": "结果验收",
        "applicable_scenes": ["故障处置", "销售推进", "招聘流程", "采购审批", "运营分析"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "任务描述 + 验收标准 + 实际结果",
        "output_format": "通过/不通过 + 问题清单 + 改进建议",
        "required_tools": [],
        "acceptance_criteria": "独立于执行者做比对，给出结构化评估",
        "description": "独立验证任务结果是否达到预期",
    },
    # --- 销售推进 ---
    {
        "skill_id": "SKILL_101",
        "skill_name": "客户画像分析",
        "applicable_scenes": ["销售推进"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "客户名称/行业/规模",
        "output_format": "画像报告",
        "required_tools": [],
        "acceptance_criteria": "覆盖行业、规模、采购偏好、决策链",
        "description": "对客户做背景和需求画像",
    },
    {
        "skill_id": "SKILL_102",
        "skill_name": "商机评估",
        "applicable_scenes": ["销售推进"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "线索描述",
        "output_format": "BANT 四维评分 + 推进建议",
        "required_tools": [],
        "acceptance_criteria": "输出结构化评分和可执行推进建议",
        "description": "按 BANT 评估商机价值",
    },
    # --- 招聘 ---
    {
        "skill_id": "SKILL_201",
        "skill_name": "简历筛选",
        "applicable_scenes": ["招聘流程"],
        "permission_level": "普通",
        "risk_level": "低",
        "input_requirements": "JD + 候选人简历",
        "output_format": "匹配分数 + 优缺点",
        "required_tools": [],
        "acceptance_criteria": "给出分数并列出匹配/不匹配项",
        "description": "按 JD 给简历打分",
    },
]


# 历史成功 Agent 模板 —— Composer 优先复用
BUILTIN_BLUEPRINTS: list[dict] = [
    {
        "blueprint_id": "BP_INCIDENT_V1",
        "scene_type": "故障处置",
        "team_composition": [
            {
                "role": "incident_commander",
                "display_name": "Incident Commander",
                "skills": ["SKILL_001", "SKILL_004", "SKILL_005"],
                "desc": "统筹：分级、通知、审批",
            },
            {
                "role": "root_cause",
                "display_name": "Root Cause Agent",
                "skills": ["SKILL_002"],
                "desc": "调查日志和监控，给根因",
            },
            {
                "role": "fix",
                "display_name": "Fix Agent",
                "skills": ["SKILL_003"],
                "desc": "给修复方案与回滚",
            },
            {
                "role": "verification",
                "display_name": "Verification Agent",
                "skills": ["SKILL_007"],
                "desc": "独立验证修复结果",
            },
        ],
        "success_rate": 0.92,
        "usage_count": 0,
        "desc": "经典故障处置四角色：IC + RC + FX + VF",
    }
]
