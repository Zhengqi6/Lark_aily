"""Seed the Skill Catalog + Agent Blueprints with the built-in defaults."""
from __future__ import annotations

from rich.console import Console

from ..skills.builtin import BUILTIN_BLUEPRINTS, BUILTIN_SKILLS
from ..storage.backend import StorageBackend, TableName

console = Console()


def seed(storage: StorageBackend, *, force: bool = False) -> tuple[int, int]:
    """Insert skills + blueprints. Skips ones already present by id.

    Returns (skills_added, blueprints_added).
    """
    storage.ensure_tables()

    existing_skills = {s.get("skill_id") for s in storage.list_records(TableName.SKILL_CATALOG)}
    skills_added = 0
    for sk in BUILTIN_SKILLS:
        if sk["skill_id"] in existing_skills and not force:
            continue
        storage.create_record(TableName.SKILL_CATALOG, dict(sk))
        skills_added += 1

    existing_bps = {b.get("blueprint_id") for b in storage.list_records(TableName.AGENT_BLUEPRINTS)}
    bps_added = 0
    for bp in BUILTIN_BLUEPRINTS:
        if bp["blueprint_id"] in existing_bps and not force:
            continue
        storage.create_record(TableName.AGENT_BLUEPRINTS, dict(bp))
        bps_added += 1

    console.print(
        f"[green]✓[/green] seeded: skills +{skills_added}, blueprints +{bps_added} "
        f"(backend={storage.kind})"
    )
    return skills_added, bps_added
