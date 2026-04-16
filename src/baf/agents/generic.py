"""Generic skill-driven agent.

When Composer invents a new role (e.g. `customer_profile_analyst` for a
sales scene), there is no specialized class registered in `DOMAIN_AGENTS`.
Rather than failing, the Orchestrator falls back to GenericAgent, which
builds its own prompt from the role spec + the bound skills in the
Skill Catalog.

This is the mechanism that makes 跨场景复用 actually work: new scenes
don't need new code — only new skill rows in the catalog.
"""
from __future__ import annotations

from typing import Any

from ..storage.backend import TableName
from .base import BaseAgent, RunContext


class GenericAgent(BaseAgent):
    role = "generic"
    display_name = "Generic Agent"
    temperature = 0.2
    json_mode = True

    def __init__(self, *args, role_spec: dict, **kw):
        super().__init__(*args, **kw)
        self.role = role_spec.get("role") or "generic"
        self.display_name = role_spec.get("display_name") or self.role
        self._role_spec = role_spec

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        # 1) resolve skills
        skill_ids = self._role_spec.get("skills") or []
        all_skills = {s["skill_id"]: s for s in self.storage.list_records(TableName.SKILL_CATALOG)}
        bound = [all_skills[sid] for sid in skill_ids if sid in all_skills]

        skill_brief = "\n".join(
            f"- {s['skill_name']}（{s.get('description','')}）"
            f"  ◇ 输入: {s.get('input_requirements','')}"
            f"  ◇ 输出: {s.get('output_format','')}"
            f"  ◇ 验收: {s.get('acceptance_criteria','')}"
            for s in bound
        ) or "（无绑定技能，按角色职责自由发挥）"

        system_prompt = f"""你是 {self.display_name}，角色编号 `{self.role}`。
职责：{self._role_spec.get('desc', '根据场景完成分派任务')}

【你绑定的技能】
{skill_brief}

【场景】{ctx.scene_type}
【已知信息】{ctx.findings}

你必须严格按以下 JSON 格式输出（不要任何多余内容）：
{{
  "deliverables": "<你产出的主要结论/内容，控制在 600 字以内>",
  "evidence": ["引用的关键线索 1", "线索 2"],
  "next_steps": ["你建议的下一步行动"],
  "confidence": 0.8
}}
"""
        user = f"【任务描述】\n{ctx.description}\n\n请按职责和技能规范给出可交付结论。"
        resp = self._chat(
            [{"role": "system", "content": system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        try:
            data = resp.as_json()
        except Exception:
            data = {"deliverables": resp.content, "evidence": [], "next_steps": [], "confidence": 0.5}
        ctx.findings[self.role] = data
        return data
