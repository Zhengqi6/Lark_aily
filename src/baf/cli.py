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


@app.command("export-report")
def export_report(
    output: str = typer.Option("report.md", "--out", "-o", help="输出 markdown 路径"),
    mock: bool = typer.Option(False, "--mock"),
):
    """Export a markdown report of all cases — for sharing or evaluator review."""
    from collections import Counter
    from pathlib import Path
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

    by_scene = Counter([c.get("scene_type") or "?" for c in cases])
    by_status = Counter([c.get("status") or "?" for c in cases])

    lines: list[str] = []
    lines.append(f"# Bitable Agent Fabric — 运行报告\n")
    lines.append(f"backend: `{storage.kind}`  ·  cases: **{len(cases)}**  ·  agent runs: **{len(runs_all)}**  ·  SOP: **{len(sops_all)}**\n")
    lines.append("## 概览\n")
    lines.append("| 场景 | 数量 |")
    lines.append("|---|---:|")
    for s, n in by_scene.most_common():
        lines.append(f"| {s} | {n} |")
    lines.append("\n| 状态 | 数量 |")
    lines.append("|---|---:|")
    for s, n in by_status.most_common():
        lines.append(f"| {s} | {n} |")
    lines.append("")

    for case in cases:
        cid = case.get("task_id", "?")
        lines.append(f"## Case `{cid}` — {case.get('title', '(no title)')}")
        lines.append(f"- scene: **{case.get('scene_type', '?')}**, severity: {case.get('severity', '-')}")
        lines.append(f"- status: **{case.get('status', '?')}**")
        if case.get("result_summary"):
            lines.append(f"- summary: {case['result_summary']}")
        lines.append("")
        lines.append("### Agent timeline")
        lines.append("| # | Agent | Status | Latency(ms) | Output |")
        lines.append("|---:|---|---|---:|---|")
        runs = sorted(
            runs_by_case.get(cid, []),
            key=lambda r: r.get("started_at") or 0,
        )
        for i, r in enumerate(runs, 1):
            out = str(r.get("output_preview") or "").replace("|", "\\|")[:160]
            lines.append(
                f"| {i} | {r.get('display_name') or r.get('agent_role', '?')} | "
                f"{r.get('status', '?')} | {r.get('latency_ms', 0)} | {out} |"
            )
        if cid in sops_by_case:
            sop = sops_by_case[cid]
            lines.append(f"\n📌 沉淀为 SOP: `{sop.get('sop_id')}` — {sop.get('title')}")
        lines.append("")

    Path(output).write_text("\n".join(lines), encoding="utf-8")
    console.print(f"[green]✓[/green] 报告已写入 {output} ({len(cases)} cases, {len(runs_all)} runs)")


if __name__ == "__main__":
    app()
