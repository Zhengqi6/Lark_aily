"""Skill Retriever — picks relevant skills for the scene.

MVP strategy: filter SkillCatalog by applicable_scenes, then (optionally)
ask the LLM to rerank the top-N. Keeps it cheap and deterministic.
"""
from __future__ import annotations

from typing import Any

from ..storage.backend import TableName
from .base import BaseAgent, RunContext


class SkillRetrieverAgent(BaseAgent):
    role = "skill_retriever"
    display_name = "Skill Retriever"
    temperature = 0.0
    json_mode = True
    is_concurrency_safe = True
    is_destructive = False
    risk_tier = "low"
    search_hint = "retrieve top-k skills for the scene"
    system_prompt = """你是 Skill Retriever。给定【场景】和【任务描述】，从候选技能清单中挑出最相关的技能，
按相关度降序返回 skill_id 列表，总数控制在 5-10 个。

输出必须是严格 JSON：{"picked":["SKILL_001","SKILL_002",...],"reasoning":"一句话"}
绝对不要输出除 JSON 以外的内容。
"""

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        assert ctx.scene_type, "scene_type must be set before SkillRetriever"

        # 1) pre-filter by scene
        all_skills = self.storage.list_records(TableName.SKILL_CATALOG)
        candidates = [
            s for s in all_skills
            if ctx.scene_type in (s.get("applicable_scenes") or [])
            or s.get("applicable_scenes") == ctx.scene_type  # string form tolerance
        ]

        # short path: too few to bother LLM
        if len(candidates) <= 5:
            ctx.skills = candidates
            return {
                "picked": [s["skill_id"] for s in candidates],
                "total_candidates": len(candidates),
                "reasoning": "候选少，直接全选",
            }

        # 2) LLM rerank
        skill_brief = "\n".join(
            f"- {s['skill_id']} | {s['skill_name']} | risk={s.get('risk_level')} | {s.get('description','')[:60]}"
            for s in candidates
        )
        user = (
            f"【场景】{ctx.scene_type}\n"
            f"【任务描述】{ctx.description}\n\n"
            f"【候选技能】\n{skill_brief}\n\n"
            "请挑选 5-10 个最相关的 skill_id。"
        )
        resp = self._chat(
            [{"role": "system", "content": self.system_prompt}, {"role": "user", "content": user}],
            ctx=ctx,
        )
        data = resp.as_json()
        picked_ids = [str(x) for x in data.get("picked", [])]
        picked = [s for s in candidates if s["skill_id"] in picked_ids]
        if not picked:  # LLM weirdness → fallback to all candidates (capped)
            picked = candidates[:10]

        ctx.skills = picked
        return {
            "picked": [s["skill_id"] for s in picked],
            "total_candidates": len(candidates),
            "reasoning": str(data.get("reasoning", ""))[:200],
        }
