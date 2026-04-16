"""Scene Router — first agent in the pipeline.

Classifies a free-form task description into one of the supported scene
types. Critical for the rest of the pipeline (skill retrieval + agent
composition both key off the scene label).
"""
from __future__ import annotations

from typing import Any

from .base import BaseAgent, RunContext

SCENES = ["故障处置", "销售推进", "招聘流程", "采购审批", "运营分析", "其他"]

SYSTEM_PROMPT = """你是 Scene Router —— 企业任务的场景路由器。
你要做的唯一一件事：把收到的任务描述分类到以下 6 个场景之一。

【支持的场景】
1. 故障处置 —— 系统宕机、服务异常、告警、CPU/内存/磁盘飙升、报错、性能问题、连接池、死锁
2. 销售推进 —— 商机、线索、客户沟通、报价、合同、转化、竞争对手
3. 招聘流程 —— 简历、面试、offer、候选人、岗位、JD
4. 采购审批 —— 供应商、报价单、采购申请、合同审批、入围
5. 运营分析 —— 数据分析、周报月报、转化率、埋点、洞察、趋势
6. 其他 —— 不属于以上任何一种

【严格输出 JSON 格式】
{
  "scene_type": "故障处置",
  "confidence": 0.93,
  "reasoning": "<30 字以内判据>",
  "need_confirmation": false
}

规则：
- confidence 必须是 0~1 的小数
- confidence < 0.7 时 need_confirmation 必须为 true
- reasoning 用中文，抓最关键的线索词（例：'出现 CPU 95%+' → 故障处置）
- 绝对不要输出除 JSON 以外的任何内容。
"""

FEW_SHOT = [
    {
        "role": "user",
        "content": "订单服务CPU使用率95%+，响应时间从200ms飙升到3000ms，影响全国用户，预计影响订单量5000+",
    },
    {
        "role": "assistant",
        "content": (
            '{"scene_type":"故障处置","confidence":0.98,'
            '"reasoning":"CPU/响应时间飙升、影响线上用户量级明确","need_confirmation":false}'
        ),
    },
    {
        "role": "user",
        "content": "今天刚接到的线索：某SaaS公司CTO想了解我们的AI平台，预算200w，年底前要落地，有竞品在对标",
    },
    {
        "role": "assistant",
        "content": (
            '{"scene_type":"销售推进","confidence":0.95,'
            '"reasoning":"明确预算/竞品/落地时间，典型商机","need_confirmation":false}'
        ),
    },
    {
        "role": "user",
        "content": "这份Python高级工程师简历帮我看一下，候选人5年经验，做过大数据",
    },
    {
        "role": "assistant",
        "content": (
            '{"scene_type":"招聘流程","confidence":0.96,'
            '"reasoning":"简历筛选请求","need_confirmation":false}'
        ),
    },
]


class SceneRouterAgent(BaseAgent):
    role = "scene_router"
    display_name = "Scene Router"
    system_prompt = SYSTEM_PROMPT
    temperature = 0.0
    json_mode = True

    def _do(self, ctx: RunContext) -> dict[str, Any]:
        messages = [{"role": "system", "content": self.system_prompt}]
        messages.extend(FEW_SHOT)
        messages.append({"role": "user", "content": ctx.description})
        resp = self._chat(messages, ctx=ctx)
        data = resp.as_json()
        scene = data.get("scene_type", "其他")
        if scene not in SCENES:
            scene = "其他"
        conf = float(data.get("confidence", 0.0))
        reasoning = str(data.get("reasoning", ""))[:200]
        need_conf = bool(data.get("need_confirmation", conf < 0.7)) or conf < 0.7

        ctx.scene_type = scene
        return {
            "scene_type": scene,
            "confidence": round(conf, 3),
            "reasoning": reasoning,
            "need_confirmation": need_conf,
        }
