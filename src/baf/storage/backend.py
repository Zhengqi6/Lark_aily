"""Storage abstraction — same interface backs both Mock and Bitable."""
from __future__ import annotations

from abc import ABC, abstractmethod
from enum import Enum
from typing import Any


class TableName(str, Enum):
    CASES = "Cases"
    SKILL_CATALOG = "SkillCatalog"
    AGENT_BLUEPRINTS = "AgentBlueprints"
    AGENT_RUNS = "AgentRuns"
    MEMORY_SOP = "MemorySOP"


class StorageBackend(ABC):
    """A flat table-oriented KV store.

    Agents and the orchestrator only talk to this interface — so the same
    orchestration code can run against local JSON (MockBackend) or the real
    Feishu Bitable (BitableBackend) without any code changes.
    """

    # --- lifecycle ---------------------------------------------------
    @abstractmethod
    def ensure_tables(self) -> None:
        """Idempotently make sure all required tables exist."""

    # --- CRUD --------------------------------------------------------
    @abstractmethod
    def create_record(self, table: TableName, fields: dict[str, Any]) -> str:
        """Return the new record's id."""

    @abstractmethod
    def update_record(self, table: TableName, record_id: str, fields: dict[str, Any]) -> None: ...

    @abstractmethod
    def get_record(self, table: TableName, record_id: str) -> dict[str, Any] | None: ...

    @abstractmethod
    def list_records(
        self, table: TableName, where: dict[str, Any] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        """Return records (each dict has `_id` plus its fields)."""

    @abstractmethod
    def delete_record(self, table: TableName, record_id: str) -> None: ...

    # --- introspection ----------------------------------------------
    @property
    @abstractmethod
    def kind(self) -> str:
        """Human label — 'mock' or 'bitable'."""

    def url_for(self, table: TableName, record_id: str | None = None) -> str | None:
        """Optional: return a user-visible URL (e.g. Feishu link)."""
        return None
