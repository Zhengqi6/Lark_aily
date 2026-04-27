"""`baf` — CLI entry point.

Commands:
    baf init            configure LLM + Feishu credentials interactively
    baf login           OAuth-authorize against Feishu (needs config first)
    baf init-tables     create 5 tables in the configured Bitable
    baf seed            insert built-in skills + blueprints
    baf run-demo        run an incident case through the full pipeline
    baf run "<desc>"    run an arbitrary case through the pipeline
    baf tables          show a summary of all 5 tables

All non-`init/login` commands accept `--mock` to use local JSON instead
of Feishu (great for offline demos).
"""
from __future__ import annotations

from typing import Optional

import typer
from rich.console import Console
from rich.prompt import Prompt

from . import __version__
from .config import Config

app = typer.Typer(add_completion=False, help="Bitable Agent Fabric CLI")
console = Console()


# ---------- helpers ------------------------------------------------
def _get_storage(use_mock: bool):
    if use_mock:
        from .storage.mock_backend import MockBackend
        mb = MockBackend()
        mb.ensure_tables()
        return mb
    # Lazy import to avoid httpx load when not needed
    from .storage.bitable_backend import BitableBackend
    cfg = Config.load()
    if not cfg.feishu_bitable_app_token:
        console.print(
            "[red]尚未配置 feishu_bitable_app_token。"
            "先运行 `baf init` 或加 --mock 在本地跑。[/red]"
        )
        raise typer.Exit(1)
    return BitableBackend(cfg)


def _get_llm():
    from .llm.client import get_default_client
    return get_default_client()


# ---------- commands -----------------------------------------------
@app.command()
def version():
    """Show version."""
    console.print(f"baf {__version__}")


@app.command()
def init():
    """Interactively set up LLM + Feishu credentials."""
    cfg = Config.load()
    console.rule("[bold cyan]Bitable Agent Fabric 初始化")

    console.print("[bold]1/2  LLM 设置[/bold]")
    cfg.llm_base_url = Prompt.ask("LLM base_url", default=cfg.llm_base_url or "https://api.zhizengzeng.com/v1/")
    cfg.llm_api_key = Prompt.ask("LLM api_key (sk-...)", default=cfg.llm_api_key or "", password=False)
    cfg.llm_model = Prompt.ask("model", default=cfg.llm_model or "gpt-4o-mini")

    console.print("\n[bold]2/2  飞书多维表格（可留空，仅 --mock 离线演示不需要）[/bold]")
    cfg.feishu_app_id = Prompt.ask("app_id", default=cfg.feishu_app_id or "")
    cfg.feishu_app_secret = Prompt.ask("app_secret", default=cfg.feishu_app_secret or "")
    cfg.feishu_bitable_app_token = Prompt.ask(
        "bitable app_token (多维表格 URL 中 /base/<这一串>)",
        default=cfg.feishu_bitable_app_token or "",
    )
    cfg.save()
    console.print(f"[green]✓[/green] 配置已保存到 ~/.baf/config.json")


@app.command()
def login():
    """Open browser to authorize against Feishu (OAuth)."""
    from .bitable.auth import oauth_login
    cfg = Config.load()
    if not (cfg.feishu_app_id and cfg.feishu_app_secret):
        console.print("[red]请先运行 `baf init` 填 app_id/app_secret。[/red]")
        raise typer.Exit(1)
    creds = oauth_login(cfg)
    console.print(
        f"[green]✓[/green] 已登录：{creds.name or creds.open_id}；"
        f"token 存于 ~/.baf/credentials.json"
    )


@app.command("init-tables")
def init_tables(
    mock: bool = typer.Option(False, "--mock", help="使用本地 JSON 后端"),
):
    """Create the 5 tables (idempotent)."""
    storage = _get_storage(mock)
    storage.ensure_tables()
    console.print(f"[green]✓[/green] tables ready on backend={storage.kind}")


@app.command()
def seed(
    mock: bool = typer.Option(False, "--mock", help="使用本地 JSON 后端"),
    force: bool = typer.Option(False, "--force", help="强制重新插入已有条目"),
):
    """Load built-in skills + blueprints into the catalog."""
    from .demo.seed_skills import seed as do_seed
    storage = _get_storage(mock)
    do_seed(storage, force=force)


@app.command("run-demo")
def run_demo(
    mock: bool = typer.Option(False, "--mock", help="使用本地 JSON 后端"),
    incident: Optional[str] = typer.Option(
        None, "--incident", help="自定义故障描述；留空走内置样例"
    ),
    title: Optional[str] = typer.Option(None, "--title", help="Case 标题"),
):
    """Run the canonical incident case through the full pipeline."""
    from .demo.demo_incident import DEFAULT_INCIDENT
    from .orchestrator import Orchestrator
    storage = _get_storage(mock)
    llm = _get_llm()
    orch = Orchestrator(llm, storage)
    case_title = title or DEFAULT_INCIDENT["title"]
    case_desc = incident or DEFAULT_INCIDENT["description"]
    result = orch.submit_case(case_title, case_desc)
    console.print(f"\n[bold]== 结果 ==[/bold]")
    console.print(f"scene   : {result.scene_type}")
    console.print(f"severity: {result.severity}")
    console.print(f"passed  : {result.passed}")
    console.print(f"summary : {result.summary}")
    url = storage.url_for_case(result.case_record_id) if hasattr(storage, "url_for_case") else None
    if url:
        console.print(f"link    : {url}")


@app.command()
def run(
    description: str = typer.Argument(..., help="任务描述（任意场景）"),
    title: str = typer.Option("Ad-hoc task", "--title"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Run an arbitrary case (any scene) through the pipeline."""
    from .orchestrator import Orchestrator
    storage = _get_storage(mock)
    llm = _get_llm()
    orch = Orchestrator(llm, storage)
    orch.submit_case(title, description)


@app.command()
def tables(
    mock: bool = typer.Option(False, "--mock"),
):
    """Show counts + a peek at each table."""
    from .storage.backend import TableName
    storage = _get_storage(mock)
    for t in TableName:
        rows = storage.list_records(t, limit=500)
        console.print(f"[cyan]{t.value}[/cyan]  rows={len(rows)}")
        for r in rows[:3]:
            compact = {k: v for k, v in r.items() if not k.startswith("_")}
            console.print(f"  • {compact}")


@app.command("demo-all")
def demo_all(
    mock: bool = typer.Option(False, "--mock", help="使用本地 JSON 后端"),
    seed_first: bool = typer.Option(True, "--seed/--no-seed", help="先 seed 内置技能/模板"),
):
    """Run all 4 canonical scenarios end-to-end (incident + sales + recruit + procure).

    评委 3 分钟 demo 路径：跑完后看 Cases/AgentRuns/MemorySOP 三表，能看到
    四种业务全部跑通，证明"同一套底座、跨场景动态编组"。
    """
    from .demo.demo_incident import DEMO_SUITE
    from .demo.seed_skills import seed as do_seed
    from .orchestrator import Orchestrator
    from rich.table import Table as RichTable

    storage = _get_storage(mock)
    if seed_first:
        do_seed(storage)
    llm = _get_llm()
    orch = Orchestrator(llm, storage)

    summary_rows: list[tuple[str, str, str, str]] = []
    for case in DEMO_SUITE:
        console.print()
        console.print(f"[bold yellow]>>> 场景预期: {case['scene_hint']}[/bold yellow]")
        result = orch.submit_case(case["title"], case["description"])
        summary_rows.append((
            case["scene_hint"],
            result.scene_type or "?",
            "✓" if result.passed else "✗",
            (result.summary or "")[:60],
        ))

    console.print()
    console.rule("[bold green]demo-all 总览")
    tbl = RichTable(show_header=True, header_style="bold cyan")
    tbl.add_column("预期场景")
    tbl.add_column("识别场景")
    tbl.add_column("结果")
    tbl.add_column("摘要")
    for r in summary_rows:
        tbl.add_row(*r)
    console.print(tbl)


@app.command()
def trace(
    case_id: str = typer.Argument(..., help="task_id (e.g. CASE_xxxxxx)"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Print the full Agent Runs timeline of a given case."""
    from rich.table import Table as RichTable
    from .storage.backend import TableName

    storage = _get_storage(mock)
    cases = storage.list_records(TableName.CASES, where={"task_id": case_id})
    if not cases:
        console.print(f"[red]找不到 case_id={case_id}[/red]")
        raise typer.Exit(1)
    case = cases[0]
    console.rule(f"[bold cyan]Case {case_id}")
    console.print(f"[dim]title :[/dim] {case.get('title')}")
    console.print(f"[dim]scene :[/dim] {case.get('scene_type')}  severity={case.get('severity')}")
    console.print(f"[dim]status:[/dim] {case.get('status')}")
    console.print(f"[dim]result:[/dim] {(case.get('result_summary') or '')[:200]}")

    runs = storage.list_records(TableName.AGENT_RUNS, where={"case_id": case_id}, limit=200)
    runs.sort(key=lambda r: r.get("started_at") or 0)
    console.print()
    tbl = RichTable(show_header=True, header_style="bold magenta")
    tbl.add_column("#", width=3)
    tbl.add_column("Agent")
    tbl.add_column("Status")
    tbl.add_column("Latency(ms)")
    tbl.add_column("Output preview")
    for i, r in enumerate(runs, 1):
        out = (r.get("output_preview") or "")[:80]
        tbl.add_row(
            str(i),
            r.get("display_name") or r.get("agent_role", "?"),
            r.get("status", "?"),
            str(r.get("latency_ms", 0)),
            out,
        )
    console.print(tbl)

    sops = storage.list_records(TableName.MEMORY_SOP, where={"source_case_id": case_id})
    if sops:
        console.print(f"\n[green]📌 已沉淀 SOP:[/green] {sops[0].get('sop_id')}  {sops[0].get('title')}")


@app.command()
def stats(
    mock: bool = typer.Option(False, "--mock"),
):
    """Aggregate stats over all cases — case count by scene + blueprint usage."""
    from rich.table import Table as RichTable
    from collections import Counter
    from .storage.backend import TableName

    storage = _get_storage(mock)
    cases = storage.list_records(TableName.CASES, limit=2000)
    runs = storage.list_records(TableName.AGENT_RUNS, limit=5000)
    bps = storage.list_records(TableName.AGENT_BLUEPRINTS, limit=200)
    sops = storage.list_records(TableName.MEMORY_SOP, limit=500)

    console.rule("[bold cyan]Bitable Agent Fabric — 运行统计")
    console.print(f"Cases: [bold]{len(cases)}[/bold]   "
                  f"AgentRuns: [bold]{len(runs)}[/bold]   "
                  f"Blueprints: [bold]{len(bps)}[/bold]   "
                  f"SOP: [bold]{len(sops)}[/bold]")

    by_scene = Counter([c.get("scene_type") or "?" for c in cases])
    by_status = Counter([c.get("status") or "?" for c in cases])

    t1 = RichTable(title="按场景", show_header=True, header_style="bold cyan")
    t1.add_column("Scene")
    t1.add_column("Cases", justify="right")
    for s, n in by_scene.most_common():
        t1.add_row(s, str(n))
    console.print(t1)

    t2 = RichTable(title="按状态", show_header=True, header_style="bold cyan")
    t2.add_column("Status")
    t2.add_column("Cases", justify="right")
    for s, n in by_status.most_common():
        t2.add_row(s, str(n))
    console.print(t2)

    t3 = RichTable(title="Blueprints", show_header=True, header_style="bold cyan")
    t3.add_column("ID")
    t3.add_column("Scene")
    t3.add_column("Usage", justify="right")
    t3.add_column("SuccessRate", justify="right")
    bps_sorted = sorted(bps, key=lambda b: -(int(b.get("usage_count") or 0)))
    for b in bps_sorted[:20]:
        t3.add_row(
            str(b.get("blueprint_id", "?")),
            str(b.get("scene_type", "?")),
            str(b.get("usage_count", 0)),
            f"{float(b.get('success_rate') or 0):.2f}",
        )
    console.print(t3)


@app.command("run-stream")
def run_stream(
    description: str = typer.Argument(..., help="任务描述"),
    title: str = typer.Option("Stream task", "--title"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Async streaming pipeline (Sprint A+B+C — Court / Approval / Evolution).

    Differences vs `run`:
      • L1→L5 layer events are emitted live as they happen
      • is_concurrency_safe agents are batched into one tick (asyncio.gather)
      • High-risk cases route through CourtAgent (3-persona vote)
      • Destructive agents (Fix) request approval; demo auto-approves
    """
    import asyncio
    from .hooks.approvals import ApprovalRegistry
    from .orchestrator_stream import StreamOrchestrator

    storage = _get_storage(mock)
    llm = _get_llm()
    approvals = ApprovalRegistry(storage)
    orch = StreamOrchestrator(llm, storage, approval_registry=approvals)

    async def _drive() -> None:
        async for ev in orch.submit_case_stream(title, description):
            console.print(f"[bold cyan]<{ev.type}>[/bold cyan] tick={ev.tick}  "
                          f"[dim]{str(ev.payload)[:160]}[/dim]")
            # Demo: auto-approve any approval requested by Fix agent.
            if ev.type == "approval_requested":
                card_id = ev.payload.get("card_id")
                if card_id:
                    approvals.auto_approve(card_id, "demo auto-approve")
                    console.print(
                        f"[yellow]✓ auto-approved {card_id} (demo)[/yellow]"
                    )

    asyncio.run(_drive())


@app.command()
def resume(
    case_id: str = typer.Argument(..., help="task_id (e.g. CASE_xxxxxx)"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Resume an interrupted streaming case from the next tick."""
    import asyncio
    from .orchestrator_stream import StreamOrchestrator

    storage = _get_storage(mock)
    llm = _get_llm()
    orch = StreamOrchestrator(llm, storage)

    async def _drive() -> None:
        async for ev in orch.run_case_stream(case_id):
            console.print(f"[bold cyan]<{ev.type}>[/bold cyan] tick={ev.tick}  "
                          f"[dim]{str(ev.payload)[:160]}[/dim]")

    asyncio.run(_drive())


@app.command()
def approve(
    card_id: str = typer.Argument(..., help="审批卡片 ID（来自 approval_requested 事件）"),
    decision: str = typer.Option("approved", "--decision",
                                  help="approved / rejected"),
    note: str = typer.Option("", "--note"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Resolve a pending approval (used when a Fix Agent paused on审批)."""
    from .hooks.approvals import ApprovalRegistry

    storage = _get_storage(mock)
    reg = ApprovalRegistry(storage)
    reg.decide(card_id, decision, note=note)
    console.print(f"[green]✓[/green] {card_id} → {decision}")


@app.command("court-test")
def court_test(
    description: str = typer.Argument(..., help="任务描述（建议为高风险故障场景）"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Standalone Court demo — invoke 3-persona critic on a synthetic context."""
    import asyncio
    from .agents.base import RunContext
    from .agents.court import CourtAgent

    storage = _get_storage(mock)
    llm = _get_llm()
    ctx = RunContext(
        case_id="COURT_TEST",
        case_record_id="-",
        description=description,
        scene_type="故障处置",
        severity="P1",
        risk_tier="high",
        skills=[],
        findings={
            "root_cause": "数据库连接池耗尽",
            "rc_evidence": ["HikariPool timeout 342 次", "active=200/200"],
            "fix_steps": [{"order": 1, "action": "扩容至 400 并重启实例"}],
            "fix_rollback": "保留旧配置，5 分钟内可回滚",
            "fix_risk": "中",
        },
    )

    async def _drive():
        court = CourtAgent(llm, storage)
        v = await court.adjudicate(ctx)
        console.print(f"[bold]passed[/bold] = {v.passed}, score={v.score:.2f}")
        for vote in v.votes:
            console.print(f"  - {vote.persona}: passed={vote.passed} "
                          f"score={vote.score:.2f}  rationale={vote.rationale[:80]}")
        if v.improvement:
            console.print(f"\n[yellow]改进建议[/yellow]: {v.improvement}")

    asyncio.run(_drive())


@app.command("export-report")
def export_report(
    output: str = typer.Option("report.md", "--out", "-o", help="输出 markdown 路径"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Export a comprehensive markdown report — DMSAS L0–L5 仪表盘版本。

    与 MVP 版的差异：
      • 顶部加 KPI 仪表盘（pass@1 / latency_p95 / cost / 自蒸馏技能数 / Blueprint EWMA）
      • Agent timeline 加 tick / parent_run_id / risk_tier / destructive 三列
      • 多个 tick 同时跑的 Agent 自动合并为「并行批次」展示
      • 新增「Court 三角色裁定」「待审批轨迹」「自蒸馏新技能」「Blueprint 进化」四个段落
    """
    import json as _json
    from collections import Counter
    from pathlib import Path
    from statistics import median
    from .storage.backend import TableName

    storage = _get_storage(mock)
    cases = storage.list_records(TableName.CASES, limit=2000)
    cases.sort(key=lambda c: c.get("created_at") or 0)
    runs_all = storage.list_records(TableName.AGENT_RUNS, limit=5000)
    runs_by_case: dict[str, list[dict]] = {}
    for r in runs_all:
        runs_by_case.setdefault(r.get("case_id") or "", []).append(r)
    sops_all = storage.list_records(TableName.MEMORY_SOP, limit=500)
    sops_by_case = {s.get("source_case_id"): s for s in sops_all}
    skills_all = storage.list_records(TableName.SKILL_CATALOG, limit=2000)
    auto_distilled = [
        s for s in skills_all if s.get("auto_distilled") or
        (s.get("skill_id") or "").startswith("SKILL_AUTO_")
    ]
    auto_by_case: dict[str, list[dict]] = {}
    for s in auto_distilled:
        auto_by_case.setdefault(s.get("source_case_id") or "", []).append(s)
    blueprints = storage.list_records(TableName.AGENT_BLUEPRINTS, limit=200)
    try:
        approvals_all = storage.list_records(TableName.PENDING_APPROVALS, limit=2000)
    except Exception:
        approvals_all = []
    approvals_by_case: dict[str, list[dict]] = {}
    for a in approvals_all:
        approvals_by_case.setdefault(a.get("case_id") or "", []).append(a)

    # ---------- KPI 计算 -------------------------------------------
    n_cases = len(cases)
    n_passed = sum(1 for c in cases if c.get("status") == "已完成")
    pass_rate = (n_passed / n_cases) if n_cases else 0.0
    latencies = [int(r.get("latency_ms") or 0) for r in runs_all if r.get("latency_ms")]
    p95 = sorted(latencies)[int(len(latencies) * 0.95) - 1] if len(latencies) >= 20 else (
        max(latencies) if latencies else 0
    )
    p50 = int(median(latencies)) if latencies else 0
    total_tokens = sum(int(r.get("token_usage") or 0) for r in runs_all)
    n_destructive = sum(1 for r in runs_all if r.get("is_destructive"))
    n_concurrent = sum(1 for r in runs_all if r.get("is_concurrency_safe"))
    by_scene = Counter([c.get("scene_type") or "?" for c in cases])
    by_status = Counter([c.get("status") or "?" for c in cases])
    by_risk = Counter([r.get("agent_risk_tier") or "low" for r in runs_all])

    lines: list[str] = []
    lines.append("# Bitable Agent Fabric — 运行报告（DMSAS L0–L5）\n")
    lines.append(
        f"backend: `{storage.kind}`  ·  cases: **{n_cases}**  ·  "
        f"agent runs: **{len(runs_all)}**  ·  SOP: **{len(sops_all)}**  ·  "
        f"自蒸馏技能: **{len(auto_distilled)}**  ·  blueprints: **{len(blueprints)}**\n"
    )

    # ---------- 1. KPI 仪表盘（横切 2 — Observability） -------------
    lines.append("## 1. KPI 仪表盘（横切 2）\n")
    lines.append("| 指标 | 值 | 说明 |")
    lines.append("|---|---:|---|")
    lines.append(f"| pass@1 | **{pass_rate:.1%}** | {n_passed}/{n_cases} 一次过 |")
    lines.append(f"| latency p50 | {p50} ms | Agent 单次调用 |")
    lines.append(f"| latency p95 | {p95} ms | 长尾观察 |")
    lines.append(f"| total tokens | {total_tokens} | 累计成本代理 |")
    lines.append(f"| destructive runs | {n_destructive} | 触发审批的 Agent 调用次数 |")
    lines.append(f"| concurrency-safe runs | {n_concurrent} | 可同 tick 并行的 Agent 调用 |")
    lines.append(f"| 自蒸馏新技能 | {len(auto_distilled)} | L5 演化产出 |")
    lines.append(f"| Blueprint 数 | {len(blueprints)} | 含 LLM 生成 + 历史模板 |")
    lines.append("")

    # ---------- 2. 场景 / 状态 / 风险等级分布 ------------------------
    lines.append("## 2. 分布概览\n")
    lines.append("| 场景 | 数量 |  | 状态 | 数量 |  | Agent 风险等级 | 调用次数 |")
    lines.append("|---|---:|---|---|---:|---|---|---:|")
    rows = max(len(by_scene), len(by_status), len(by_risk))
    keys_scene = list(by_scene.most_common())
    keys_status = list(by_status.most_common())
    keys_risk = list(by_risk.most_common())
    for i in range(rows):
        s = keys_scene[i] if i < len(keys_scene) else ("", "")
        st = keys_status[i] if i < len(keys_status) else ("", "")
        r = keys_risk[i] if i < len(keys_risk) else ("", "")
        lines.append(
            f"| {s[0]} | {s[1]} |  | {st[0]} | {st[1]} |  | {r[0]} | {r[1]} |"
        )
    lines.append("")

    # ---------- 3. Blueprint 进化 ------------------------------------
    lines.append("## 3. Blueprint 进化树（L5 — EWMA α=0.3）\n")
    lines.append("| Blueprint ID | 场景 | 使用次数 | success_rate (EWMA) | 备注 |")
    lines.append("|---|---|---:|---:|---|")
    for bp in sorted(blueprints, key=lambda b: -float(b.get("success_rate") or 0)):
        lines.append(
            f"| `{bp.get('blueprint_id','?')}` | {bp.get('scene_type','?')} | "
            f"{bp.get('usage_count', 0)} | {float(bp.get('success_rate') or 0):.3f} | "
            f"{(bp.get('desc') or '')[:60]} |"
        )
    lines.append("")

    # ---------- 4. 每个 case 的详细轨迹 -----------------------------
    for case in cases:
        cid = case.get("task_id", "?")
        lines.append(f"## Case `{cid}` — {case.get('title', '(no title)')}")
        lines.append(
            f"- scene: **{case.get('scene_type', '?')}**, "
            f"severity: {case.get('severity', '-')}, "
            f"status: **{case.get('status', '?')}**"
        )
        if case.get("result_summary"):
            lines.append(f"- summary: {case['result_summary']}")
        if case.get("agent_team"):
            lines.append(f"- team: `{case.get('agent_team')}`")
        lines.append("")

        runs = sorted(
            runs_by_case.get(cid, []),
            key=lambda r: (int(r.get("tick") or 0), r.get("started_at") or 0),
        )

        # 4.1 按 tick 分组的并行批次（L3 — Tick + asyncio.gather）
        if any(r.get("tick") for r in runs):
            lines.append("### 4.1 Tick 调度（同 tick = 并行）")
            from collections import defaultdict
            by_tick: dict[int, list[dict]] = defaultdict(list)
            for r in runs:
                by_tick[int(r.get("tick") or 0)].append(r)
            lines.append("| Tick | 并行/串行 | Agents | 风险 |")
            lines.append("|---:|---|---|---|")
            for tk in sorted(by_tick.keys()):
                grp = by_tick[tk]
                kind = "并行" if (len(grp) > 1 and all(g.get("is_concurrency_safe") for g in grp)) else "串行"
                names = ", ".join(g.get("display_name") or g.get("agent_role", "?") for g in grp)
                risks = ",".join(sorted({g.get("agent_risk_tier") or "low" for g in grp}))
                lines.append(f"| {tk} | {kind} | {names} | {risks} |")
            lines.append("")

        # 4.2 详细 timeline（带元数据列）
        lines.append("### 4.2 Agent timeline（含 Sprint A 元数据）")
        lines.append("| # | Tick | Agent | Status | Risk | Destructive | ms | Tokens | Output |")
        lines.append("|---:|---:|---|---|---|:---:|---:|---:|---|")
        for i, r in enumerate(runs, 1):
            out = str(r.get("output_preview") or "").replace("|", "\\|")[:140]
            destr = "💥" if r.get("is_destructive") else ""
            lines.append(
                f"| {i} | {r.get('tick', 0) or '-'} | "
                f"{r.get('display_name') or r.get('agent_role', '?')} | "
                f"{r.get('status', '?')} | {r.get('agent_risk_tier', 'low')} | "
                f"{destr} | {r.get('latency_ms', 0)} | {r.get('token_usage', 0)} | "
                f"{out} |"
            )
        lines.append("")

        # 4.3 Court verdict (L4 — 三角色法庭)
        court_verdict = _extract_court_verdict(runs)
        if court_verdict:
            lines.append("### 4.3 Court 三角色裁定（L4）")
            lines.append(f"- passed: **{court_verdict.get('passed')}**, "
                         f"score: {court_verdict.get('score')}, "
                         f"summary: {court_verdict.get('summary','')[:120]}")
            votes = court_verdict.get("votes") or []
            if votes:
                lines.append("\n| Persona | Passed | Score | Rationale |")
                lines.append("|---|:---:|---:|---|")
                for v in votes:
                    lines.append(
                        f"| {v.get('persona')} | "
                        f"{'✓' if v.get('passed') else '✗'} | "
                        f"{float(v.get('score') or 0):.2f} | "
                        f"{(v.get('rationale') or '')[:80]} |"
                    )
            if court_verdict.get("improvement"):
                lines.append(f"\n> 改进建议: {court_verdict['improvement'][:200]}")
            lines.append("")

        # 4.4 待审批 / 审批轨迹 (Sprint B)
        case_apvs = approvals_by_case.get(cid, [])
        if case_apvs:
            lines.append("### 4.4 异步审批轨迹（Sprint B — Async Hook）")
            lines.append("| Card ID | 状态 | 决策备注 | 触发 Agent run |")
            lines.append("|---|---|---|---|")
            for a in case_apvs:
                lines.append(
                    f"| `{a.get('card_id','')}` | {a.get('status','?')} | "
                    f"{(a.get('decision_note') or '')[:60]} | "
                    f"{a.get('agent_run_id','')} |"
                )
            lines.append("")

        # 4.5 自蒸馏新技能 (L5)
        case_skills = auto_by_case.get(cid, [])
        if case_skills:
            lines.append("### 4.5 自蒸馏新技能（L5 — Skill Library 自演化）")
            for s in case_skills:
                tools = ",".join(s.get("required_tools") or [])
                lines.append(
                    f"- ✨ `{s.get('skill_id')}` — {s.get('skill_name')} "
                    f"（tools: {tools}）"
                )
            lines.append("")

        # 4.6 SOP
        if cid in sops_by_case:
            sop = sops_by_case[cid]
            lines.append("### 4.6 SOP 沉淀")
            lines.append(f"- 📌 `{sop.get('sop_id')}` — {sop.get('title')}")
            if sop.get("narrative"):
                lines.append(f"- narrative: {sop.get('narrative')[:200]}")
            kd = sop.get("key_decisions")
            if kd:
                lines.append(f"- key decisions: `{kd}`")
            lines.append("")
        lines.append("")

    Path(output).write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]✓[/green] 报告已写入 {output} ({len(cases)} cases, {len(runs_all)} runs)")


def _extract_court_verdict(runs: list[dict]) -> dict | None:
    """Pull the Court Agent's verdict (or the fast-verify result) from
    `output_preview` of the matching AgentRuns row."""
    import json as _json
    for r in runs:
        role = r.get("agent_role") or ""
        if role not in {"court", "verification"}:
            continue
        preview = r.get("output_preview")
        if not isinstance(preview, str):
            continue
        try:
            data = _json.loads(preview)
        except Exception:
            continue
        if isinstance(data, dict) and (
            "votes" in data or "passed" in data
        ):
            return data
    return None


if __name__ == "__main__":
    app()
