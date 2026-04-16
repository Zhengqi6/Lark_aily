"""Minimal Bitable REST client.

Docs: https://open.feishu.cn/document/server-docs/docs/bitable-v1/overview

Only the endpoints we actually need:
  - GET    /bitable/v1/apps/{app_token}                                         → app meta
  - GET    /bitable/v1/apps/{app_token}/tables                                  → list tables
  - POST   /bitable/v1/apps/{app_token}/tables                                  → create table
  - POST   /bitable/v1/apps/{app_token}/tables/{table_id}/fields                → add field
  - POST   /bitable/v1/apps/{app_token}/tables/{table_id}/records               → create record
  - PATCH  /bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}   → update record
  - GET    /bitable/v1/apps/{app_token}/tables/{table_id}/records               → list records
  - DELETE /bitable/v1/apps/{app_token}/tables/{table_id}/records/{record_id}   → delete record
  - GET    /bitable/v1/apps/{app_token}/tables/{table_id}/fields                → list fields
"""
from __future__ import annotations

import time
from typing import Any

import httpx

from ..config import Config
from .auth import ensure_user_token, get_app_access_token

FEISHU_BASE = "https://open.feishu.cn"


class BitableAPIError(RuntimeError):
    def __init__(self, code: int, msg: str, payload: dict | None = None):
        super().__init__(f"[{code}] {msg}")
        self.code = code
        self.msg = msg
        self.payload = payload or {}


class BitableClient:
    """Thin typed wrapper over Feishu Bitable REST API.

    Auth: prefers user_access_token (OAuth), falls back to app_access_token
    (tenant-level). user_access_token gives the best UX: permissions equal
    to the end user, and records show the real author.
    """

    def __init__(self, cfg: Config, app_token: str | None = None, prefer_user: bool = True):
        self._cfg = cfg
        self.app_token = app_token or cfg.feishu_bitable_app_token
        if not self.app_token:
            raise RuntimeError("feishu_bitable_app_token 未配置")
        self._prefer_user = prefer_user
        self._http = httpx.Client(timeout=30)

    # ---- auth ------------------------------------------------------
    def _auth_header(self) -> dict[str, str]:
        try:
            if self._prefer_user:
                tok = ensure_user_token(self._cfg)
                return {"Authorization": f"Bearer {tok}"}
        except Exception:
            pass
        # fallback: tenant / app token
        tok = get_app_access_token(self._cfg)
        return {"Authorization": f"Bearer {tok}"}

    # ---- generic ---------------------------------------------------
    def _request(self, method: str, path: str, *, json: Any = None, params: dict | None = None) -> dict:
        url = f"{FEISHU_BASE}{path}"
        last: httpx.Response | None = None
        for attempt in range(3):
            headers = {"Content-Type": "application/json", **self._auth_header()}
            r = self._http.request(method, url, headers=headers, json=json, params=params)
            last = r
            if r.status_code == 401 and attempt == 0:
                # token might be stale — small backoff and retry
                time.sleep(0.5)
                continue
            try:
                body = r.json()
            except Exception:
                r.raise_for_status()
                raise
            if body.get("code") == 0:
                return body.get("data", {})
            # retry on transient
            if body.get("code") in (99991663, 99991668) and attempt < 2:  # rate-limit codes, if any
                time.sleep(1 + attempt)
                continue
            raise BitableAPIError(body.get("code", -1), body.get("msg", "unknown"), body)
        r = last  # pragma: no cover
        r.raise_for_status() if r is not None else None
        raise RuntimeError("unreachable")

    # ---- tables ----------------------------------------------------
    def list_tables(self) -> list[dict]:
        data = self._request("GET", f"/open-apis/bitable/v1/apps/{self.app_token}/tables", params={"page_size": 100})
        return data.get("items", [])

    def create_table(self, name: str, fields: list[dict] | None = None) -> str:
        """Create a table with given name. Returns table_id."""
        payload: dict[str, Any] = {"table": {"name": name}}
        if fields:
            payload["table"]["default_view_name"] = "Grid"
            payload["table"]["fields"] = fields
        data = self._request("POST", f"/open-apis/bitable/v1/apps/{self.app_token}/tables", json=payload)
        return data.get("table_id", "")

    def list_fields(self, table_id: str) -> list[dict]:
        data = self._request(
            "GET",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields",
            params={"page_size": 100},
        )
        return data.get("items", [])

    def add_field(self, table_id: str, field: dict) -> str:
        data = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/fields",
            json=field,
        )
        return data.get("field", {}).get("field_id", "")

    # ---- records ---------------------------------------------------
    def create_record(self, table_id: str, fields: dict) -> str:
        data = self._request(
            "POST",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records",
            json={"fields": fields},
        )
        return data.get("record", {}).get("record_id", "")

    def update_record(self, table_id: str, record_id: str, fields: dict) -> None:
        self._request(
            "PUT",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}",
            json={"fields": fields},
        )

    def get_record(self, table_id: str, record_id: str) -> dict | None:
        try:
            data = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}",
            )
            return data.get("record")
        except BitableAPIError:
            return None

    def list_records(self, table_id: str, *, page_size: int = 200, filter_expr: str | None = None) -> list[dict]:
        params: dict[str, Any] = {"page_size": min(page_size, 500)}
        if filter_expr:
            params["filter"] = filter_expr
        items: list[dict] = []
        page_token: str | None = None
        while True:
            if page_token:
                params["page_token"] = page_token
            data = self._request(
                "GET",
                f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records",
                params=params,
            )
            items.extend(data.get("items", []))
            if not data.get("has_more") or len(items) >= page_size:
                break
            page_token = data.get("page_token")
            if not page_token:
                break
        return items[:page_size]

    def delete_record(self, table_id: str, record_id: str) -> None:
        self._request(
            "DELETE",
            f"/open-apis/bitable/v1/apps/{self.app_token}/tables/{table_id}/records/{record_id}",
        )

    # ---- util ------------------------------------------------------
    def app_url(self, table_id: str | None = None) -> str:
        base = f"https://www.feishu.cn/base/{self.app_token}"
        return f"{base}?table={table_id}" if table_id else base
