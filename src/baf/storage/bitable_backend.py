"""Bitable-backed StorageBackend.

Maps the abstract TableName enum to real Bitable table_ids. On first
use it scans the target app for tables matching our display names; if
any are missing it creates them from SCHEMAS.

Translation rules (Python dict → Bitable field value):
  - lists (other than known multi-select fields) → JSON string
  - datetimes (float unix seconds) → int unix millis (Bitable type 5)
  - strings / numbers / booleans pass through
"""
from __future__ import annotations

import json
import time
from typing import Any

from ..bitable.client import BitableAPIError, BitableClient
from ..bitable.schemas import SCHEMAS, TABLE_DISPLAY_NAMES
from ..config import Config
from .backend import StorageBackend, TableName


# Fields that are legitimately lists in Bitable (multi-select).
_MULTI_SELECT_FIELDS = {"applicable_scenes"}
# Fields stored as int unix-millis.
_DATETIME_FIELDS = {
    "created_at", "closed_at", "started_at",
    "requested_at", "expires_at", "decided_at",
}


def _to_bitable(fields: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for k, v in fields.items():
        if k.startswith("_") or v is None or v == "":
            continue
        if k in _DATETIME_FIELDS and isinstance(v, (int, float)):
            out[k] = int(v * 1000)
            continue
        if isinstance(v, list):
            if k in _MULTI_SELECT_FIELDS:
                out[k] = [str(x) for x in v]
            else:
                out[k] = json.dumps(v, ensure_ascii=False)
            continue
        if isinstance(v, dict):
            out[k] = json.dumps(v, ensure_ascii=False)
            continue
        out[k] = v
    return out


def _from_bitable(fields: dict[str, Any]) -> dict[str, Any]:
    """Coerce Bitable-returned fields back toward Python-native values."""
    out: dict[str, Any] = {}
    for k, v in fields.items():
        # multi-select sometimes comes as [{"name":"故障处置"}, ...]
        if isinstance(v, list) and v and isinstance(v[0], dict) and "name" in v[0]:
            out[k] = [item.get("name") for item in v]
            continue
        # single-select can come as {"name": "P1"}
        if isinstance(v, dict) and set(v.keys()) == {"name"}:
            out[k] = v.get("name")
            continue
        if k in _DATETIME_FIELDS and isinstance(v, (int, float)):
            out[k] = v / 1000.0
            continue
        # JSON-encoded lists stored as strings → try to parse
        if isinstance(v, str) and (v.startswith("[") or v.startswith("{")):
            try:
                out[k] = json.loads(v)
                continue
            except Exception:
                pass
        # text cells sometimes arrive as [{"type":"text","text":"..."}]
        if isinstance(v, list) and v and isinstance(v[0], dict) and "text" in v[0]:
            out[k] = "".join(str(x.get("text", "")) for x in v)
            continue
        out[k] = v
    return out


class BitableBackend(StorageBackend):
    def __init__(self, cfg: Config):
        self._cfg = cfg
        self._client = BitableClient(cfg)
        self._table_ids: dict[TableName, str] = {}

    @property
    def kind(self) -> str:
        return "bitable"

    # ---- table discovery / creation --------------------------------
    def _discover(self) -> dict[str, str]:
        existing = self._client.list_tables()
        return {t["name"]: t["table_id"] for t in existing}

    def ensure_tables(self) -> None:
        existing = self._discover()
        for t, display in TABLE_DISPLAY_NAMES.items():
            # Accept either the friendly display name or the enum value.
            tid = existing.get(display) or existing.get(t.value)
            if not tid:
                fields = [f.to_api() for f in SCHEMAS[t]]
                tid = self._client.create_table(display, fields=fields)
            self._table_ids[t] = tid

    def _tid(self, table: TableName) -> str:
        if table not in self._table_ids:
            self.ensure_tables()
        return self._table_ids[table]

    # ---- CRUD ------------------------------------------------------
    def create_record(self, table: TableName, fields: dict[str, Any]) -> str:
        payload = _to_bitable(fields)
        # ensure created_at if not supplied (helps grid-default sort)
        if table == TableName.CASES and "created_at" not in payload:
            payload["created_at"] = int(time.time() * 1000)
        try:
            return self._client.create_record(self._tid(table), payload)
        except BitableAPIError as e:
            # If a single-select option doesn't exist, fall back to text (skip unknown)
            if e.code in (1254045, 1254046):   # unknown option codes (best-effort)
                payload = {k: v for k, v in payload.items() if not isinstance(v, str) or len(v) < 200}
                return self._client.create_record(self._tid(table), payload)
            raise

    def update_record(self, table: TableName, record_id: str, fields: dict[str, Any]) -> None:
        payload = _to_bitable(fields)
        self._client.update_record(self._tid(table), record_id, payload)

    def get_record(self, table: TableName, record_id: str) -> dict[str, Any] | None:
        rec = self._client.get_record(self._tid(table), record_id)
        if not rec:
            return None
        return {"_id": rec.get("record_id"), **_from_bitable(rec.get("fields", {}))}

    def list_records(
        self, table: TableName, where: dict[str, Any] | None = None, limit: int = 200
    ) -> list[dict[str, Any]]:
        items = self._client.list_records(self._tid(table), page_size=limit)
        rows = [{"_id": it.get("record_id"), **_from_bitable(it.get("fields", {}))} for it in items]
        if where:
            def match(row: dict[str, Any]) -> bool:
                for k, v in where.items():
                    rv = row.get(k)
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
        return rows

    def delete_record(self, table: TableName, record_id: str) -> None:
        self._client.delete_record(self._tid(table), record_id)

    # ---- URLs ------------------------------------------------------
    def url_for(self, table: TableName, record_id: str | None = None) -> str | None:
        tid = self._table_ids.get(table)
        return self._client.app_url(tid)

    def url_for_case(self, record_id: str) -> str | None:
        return self._client.app_url(self._table_ids.get(TableName.CASES))
