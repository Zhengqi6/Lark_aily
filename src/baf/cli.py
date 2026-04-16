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


if __name__ == "__main__":
    app()
