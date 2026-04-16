"""Agent Composer — designs the agent team for this case.

Strategy: prefer reusing existing AgentBlueprints for the scene; only
fall back to LLM "from-scratch" design when no blueprint exists yet.
After a successful run, Composer will bump the blueprint's usage count
so "popular templates" naturally float to the top.
"""
from __future__ import annotations

from typing import Any

from ..storage.backend import TableName
from .base import BaseAgent, RunContext


class AgentComposerAgent(BaseAgent):
    role = "composer"
    display_name = "Agent Composer"
    temperature = 0.2
    json_mode = True
    system_prompt = """你是 Agent Composer —— 负责给定场景和可用技能，设计一支 agent 团队。
每个 agent 必须：
  - 有明确的 role (英文 snake_case) 和 display_name (中文)
  - 绑定 1-5 个 skill_id
  - 有一句 desc 说明职责边界

输出严格 JSON：
{
  "team":[
    {"role":"incident_commander","display_name":"Incident Commander","skills":["SKILL_001"],"desc":"..."}
  ],
  "reasoning":"为什么这样编组"
}
绝对不要输出除 JSON 以外的内容。
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        assert ctx.scene_type, "scene_type must be set"

        # 1) look for existing blueprint
        blueprints = self.storage.list_records(
            TableName.AGENT_BLUEPRINTS, where={"scene_type": ctx.scene_type}
        )
        if blueprints:
            # pick highest success_rate
            bp = max(blueprints, key=lambda x: float(x.get("success_rate", 0) or 0))
            team = bp.get("team_composition") or []
            ctx.team = team
            # bump usage
            self.storage.update_record(
                TableName.AGENT_BLUEPRINTS,
                bp["_id"],
                {"usage_count": int(bp.get("usage_count", 0) or 0) + 1},
            )
            # remember which blueprint we used so the orchestrator can update its success_rate
            ctx.blackboard["blueprint_id"] = bp.get("blueprint_id")
            ctx.blackboard["blueprint_record_id"] = bp["_id"]
            return {
                "source": "blueprint",
                "blueprint_id": bp.get("blueprint_id"),
                "team": team,
                "reasoning": f"复用历史模板 {bp.get('blueprint_id')}（成功率 {bp.get('success_rate')})",
            }

        # 2) LLM design from scratch
        skill_brief = "\n".join(
            f"- {s['skill_id']} | {s['skill_name']} | {s.get('description','')[:60]}"
            for s in ctx.skills
        )
        user = (
            f"【场景】{ctx.scene_type}\n"
            f"【任务描述】{ctx.description}\n\n"
            f"【可用技能】\n{skill_brief}\n\n"
            "请设计一支合适的 agent 团队（2-5 个角色），每个角色只挑最相关技能。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        team = data.get("team") or []
        ctx.team = team

        # persist as a new blueprint for future reuse
        if team:
            new_bp_id = f"BP_{ctx.scene_type}_{ctx.case_id[:8]}"
            rec_id = self.storage.create_record(
                TableName.AGENT_BLUEPRINTS,
                {
                    "blueprint_id": new_bp_id,
                    "scene_type": ctx.scene_type,
                    "team_composition": team,
                    "success_rate": 0.0,   # updated after case closes
                    "usage_count": 1,
                    "desc": str(data.get("reasoning", ""))[:200],
                },
            )
            ctx.blackboard["blueprint_id"] = new_bp_id
            ctx.blackboard["blueprint_record_id"] = rec_id

        return {
            "source": "llm",
            "team": team,
            "reasoning": str(data.get("reasoning", ""))[:200],
        }
