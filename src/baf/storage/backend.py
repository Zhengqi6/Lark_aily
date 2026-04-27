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
    PENDING_APPROVALS = "PendingApprovals"  # Sprint B: 异步审批


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

    # --- Sprint A extras: tick / vector / resume ---------------------
    def get_max_tick(self, case_id: str) -> int:
        """Return the largest tick value previously written for this case.

        Used by the async generator orchestrator to resume from the next tick
        when a long-running task is restarted.
        """
        runs = self.list_records(TableName.AGENT_RUNS, where={"case_id": case_id}, limit=2000)
        return max((int(r.get("tick") or 0) for r in runs), default=0)

    def vector_search(
        self, table: TableName, query_vec: list[float], top_k: int = 20
    ) -> list[dict[str, Any]]:
        """Cosine-similarity search over the table's `embedding` column.

        Default implementation does a Python-side scan — fine for the
        Mock/Bitable demo scale (≤ a few thousand rows). Production would
        push this into a real vector store.
        """
        import math
        rows = self.list_records(table, limit=2000)
        scored: list[tuple[float, dict[str, Any]]] = []
        qn = math.sqrt(sum(x * x for x in query_vec)) or 1.0
        for r in rows:
            emb = r.get("embedding")
            if isinstance(emb, str):
                try:
                    import json as _j
                    emb = _j.loads(emb)
                except Exception:
                    emb = None
            if not isinstance(emb, list) or not emb:
                continue
            try:
                rn = math.sqrt(sum(float(x) * float(x) for x in emb)) or 1.0
                dot = sum(float(a) * float(b) for a, b in zip(query_vec, emb))
                scored.append((dot / (qn * rn), r))
            except Exception:
                continue
        scored.sort(key=lambda x: -x[0])
        return [r for _, r in scored[:top_k]]
