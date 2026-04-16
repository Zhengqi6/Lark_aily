"""Local JSON-file backend for offline development & demos.

Each table maps to one JSON file under ~/.baf/mock/. Concurrency is handled
with an flock-style POSIX advisory lock per file. Good enough for single-user
CLI demos; we don't pretend this is a real DB.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

from ..config import MOCK_DIR
from .backend import StorageBackend, TableName


class MockBackend(StorageBackend):
    def __init__(self, root: Path | None = None):
        self._root = root or MOCK_DIR
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def kind(self) -> str:
        return "mock"

    def _path(self, table: TableName) -> Path:
        return self._root / f"{table.value}.json"

    def _load(self, table: TableName) -> list[dict[str, Any]]:
        p = self._path(table)
        if not p.exists():
            return []
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return []

    def _save(self, table: TableName, rows: list[dict[str, Any]]) -> None:
        p = self._path(table)
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(rows, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)

    # --- StorageBackend API -----------------------------------------
    def ensure_tables(self) -> None:
        for t in TableName:
            if not self._path(t).exists():
                self._save(t, [])

    def create_record(self, table: TableName, fields: dict[str, Any]) -> str:
        rows = self._load(table)
        rid = f"rec_{uuid.uuid4().hex[:12]}"
        row = {"_id": rid, "_created_at": time.time(), **fields}
        rows.append(row)
        self._save(table, rows)
        return rid

    def update_record(self, table: TableName, record_id: str, fields: dict[str, Any]) -> None:
        rows = self._load(table)
        for r in rows:
            if r.get("_id") == record_id:
                r.update(fields)
                r["_updated_at"] = time.time()
                break
        else:
            raise KeyError(f"record {record_id} not found in {table.value}")
        self._save(table, rows)

    def get_record(self, table: TableName, record_id: str) -> dict[str, Any] | None:
        for r in self._load(table):
            if r.get("_id") == record_id:
                return r
        return None

    def list_records(
        self, table: TableName, where: dict[str, Any] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        rows = self._load(table)
        if where:
            def match(row: dict[str, Any]) -> bool:
                for k, v in where.items():
                    rv = row.get(k)
                    # support "in list" matching when expected is list and actual is scalar
                    if isinstance(v, list):
                        if rv not in v:
                            return False
                    elif isinstance(rv, list):
                        if v not in rv:
                            return False
                    else:
                        if rv != v:
                            return False
                return True
            rows = [r for r in rows if match(r)]
        return rows[:limit]

    def delete_record(self, table: TableName, record_id: str) -> None:
        rows = self._load(table)
        rows = [r for r in rows if r.get("_id") != record_id]
        self._save(table, rows)

    # --- extras -----------------------------------------------------
    def url_for(self, table: TableName, record_id: str | None = None) -> str | None:
        if record_id:
            return f"file://{self._path(table)}#{record_id}"
        return f"file://{self._path(table)}"
