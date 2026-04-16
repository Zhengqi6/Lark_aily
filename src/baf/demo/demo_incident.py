"""Canned incident descriptions used by `baf run-demo`."""
from __future__ import annotations

DEFAULT_INCIDENT = {
    "title": "订单服务响应超时，疑似数据库连接池耗尽",
    "description": (
        "【告警时间】2026-04-16 10:30:00\n"
        "【现象】订单服务 CPU 持续 95%+，接口 P99 响应时间从 200ms 飙升到 3000ms+。"
        "【影响】全国用户下单失败，过去 10 分钟影响订单量约 5000+。\n"
        "【监控】order-service db.connections.active=200/200，pending=45；"
        "thread_pool_saturation=0.98。\n"
        "【日志摘要】大量 'HikariPool: Connection is not available, request timed out after 30000ms'。\n"
        "【诉求】请尽快定位根因并给出修复方案。"
    ),
}

EXTRA_CASES = [
    {
        "title": "海淀工厂产线监控数据异常",
        "description": "海淀工厂 A 产线 MES 连续 3 分钟未上报数据，现场质检员反馈看板一直转圈。",
    },
    {
        "title": "销售线索：某 SaaS CTO 咨询 AI 平台",
        "description": "某 SaaS 公司 CTO 表示有预算 200w 想在年底前落地 AI 平台，正在对比 3 家竞品。",
    },
]


# 多场景串联演示用 —— `baf demo-all` 会顺序跑这一组
DEMO_SUITE = [
    {
        "scene_hint": "故障处置",
        "title": DEFAULT_INCIDENT["title"],
        "description": DEFAULT_INCIDENT["description"],
    },
    {
        "scene_hint": "销售推进",
        "title": "深入推进 G 客户 AI 平台商机",
        "description": (
            "G 公司是 200 人规模的医疗 SaaS，CTO 王总今天电话沟通：年底前预算 200w 想落地"
            "AI 客服 + 内部知识库；正在对比我们和另外 2 家竞品；他们关心数据本地化、"
            "私有部署、合规审计；下周三董事会上他要 pitch。请帮我们出一份完整的跟进方案。"
        ),
    },
    {
        "scene_hint": "招聘流程",
        "title": "高级前端工程师 - 候选人 A 评估",
        "description": (
            "JD：5 年以上 React/TypeScript，主导过 B 端 SaaS 设计系统、有微前端经验、"
            "薪酬带宽 35-55K * 16。候选人 A 简历：6 年经验，前 2 段在创业公司做 B 端 ERP，"
            "近 2 年在大厂做营销中台，主导过 monorepo 改造，自述年薪 50w。"
            "请筛简历、出针对性面试题、给 offer 谈判建议。"
        ),
    },
    {
        "scene_hint": "采购审批",
        "title": "市场部采购 200 套远程会议设备",
        "description": (
            "市场部申请采购 200 套高清远程会议麦克风+摄像头，预算单价 1500、总价 30 万；"
            "供应商初选：罗技 (单价 1620, 交期 30天, 资质完整)，雷蛇 (单价 1450, 交期 45天,"
            "缺乏 3C 认证)，国产 X 牌 (单价 1180, 交期 20天, 资质完整但案例较少)。"
            "请按公司采购规章评估并给推荐。"
        ),
    },
]
