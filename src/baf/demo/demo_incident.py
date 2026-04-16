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
