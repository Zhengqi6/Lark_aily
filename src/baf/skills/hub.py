"""Skill Hub — unified skill gateway.

Three responsibilities (DMSAS_Design.md §横切 1):
  1. Vector / lexical retrieval over the Skill Catalog
  2. MCP-style adapter dispatch (`hub.invoke(skill_id, args, ctx)`)
  3. Policy engine: permission / risk / rate-limit / approval

The MVP keeps things deliberately simple:
  - Vector index = bag-of-keyword TF over the catalog (no model dep);
    swap with sentence-transformers in production.
  - MCP adapter = registry of `tool_name -> callable`; defaults to a few
    mocked impls so the demo runs offline.
  - Policy = a small whitelist + `risk_tier` gating; `ask` results bubble
    up to ApprovalRegistry.
"""
from __future__ import annotations

import math
import re
import time
from collections import Counter
from dataclasses import dataclass
from typing import Any, Callable

from ..storage.backend import StorageBackend, TableName


_STOP = set("的 了 我 你 它 是 这 那 a an the of and or to in on for is are with".split())


def _tokenize(text: str) -> list[str]:
    if not text:
        return []
    # Coarse Chinese + ASCII tokenization — fine for demo retrieval.
    text = text.lower()
    parts = re.findall(r"[A-Za-z0-9_]+|[\u4e00-\u9fa5]", text)
    return [p for p in parts if p not in _STOP]


def _score_lexical(query_tokens: list[str], doc: str) -> float:
    if not query_tokens or not doc:
        return 0.0
    doc_tokens = _tokenize(doc)
    if not doc_tokens:
        return 0.0
    cnt = Counter(doc_tokens)
    return sum(cnt.get(q, 0) for q in query_tokens) / math.sqrt(len(doc_tokens))


@dataclass
class Skill:
    id: str
    name: str
    description: str
    risk_level: str
    permission_level: str
    applicable_scenes: list[str]
    raw: dict[str, Any]


class SkillHub:
    """Retrieve / govern / invoke skills."""

    def __init__(
        self,
        storage: StorageBackend,
        mcp_clients: dict[str, Callable[[str, dict], Any]] | None = None,
        embedder: Callable[[str], list[float]] | None = None,
    ):
        self.storage = storage
        self.mcp = mcp_clients or _default_mcp_clients()
        self.embedder = embedder

    # ---- retrieve --------------------------------------------------
    def retrieve(self, query: str, *, scene: str | None = None, top_k: int = 8) -> list[Skill]:
        """Two-stage retrieval (DMSAS_Design.md §三.亮点 2 — Tool RAG).

        Stage 1 (cheap): pre-filter by scene + lexical score on
        `name + search_hint + risk_level` (a 5-10 word view).
        Stage 2 (precise): if an embedder is configured, rerank with
        cosine similarity over the catalog's `embedding` column. The
        rest of the schema (`description`, `input_schema`) is only loaded
        for the survivors — that's the deferred-schema trick lifted from
        Claude Code's `ToolSearch`.
        """
        rows = self.storage.list_records(TableName.SKILL_CATALOG, limit=2000)
        if scene:
            rows = [
                r for r in rows
                if scene in (r.get("applicable_scenes") or [])
                or r.get("applicable_scenes") == scene
            ]
        # Stage 1: lexical short-form ranking
        q_tokens = _tokenize(query)
        ranked: list[tuple[float, dict[str, Any]]] = []
        for r in rows:
            short = " ".join([
                str(r.get("skill_name") or ""),
                str(r.get("search_hint") or r.get("description") or "")[:80],
                str(r.get("risk_level") or ""),
            ])
            ranked.append((_score_lexical(q_tokens, short), r))
        # ensure deterministic fallback ordering when the score is 0
        ranked.sort(key=lambda x: (-x[0], x[1].get("skill_id", "")))

        finalists = [r for _, r in ranked[: max(top_k * 3, top_k)]]

        # Stage 2 (optional): embedding rerank
        if self.embedder is not None and finalists:
            try:
                qv = self.embedder(query)
                with_vec = [(self._cosine(qv, r.get("embedding")), r) for r in finalists]
                with_vec.sort(key=lambda x: -x[0])
                finalists = [r for _, r in with_vec]
            except Exception:
                pass

        return [self._wrap(r) for r in finalists[:top_k]]

    @staticmethod
    def _cosine(a: list[float], b: Any) -> float:
        if not isinstance(b, list) or not b:
            return 0.0
        try:
            an = math.sqrt(sum(x * x for x in a)) or 1.0
            bn = math.sqrt(sum(float(x) * float(x) for x in b)) or 1.0
            return sum(float(x) * float(y) for x, y in zip(a, b)) / (an * bn)
        except Exception:
            return 0.0

    @staticmethod
    def _wrap(row: dict[str, Any]) -> Skill:
        return Skill(
            id=row.get("skill_id", ""),
            name=row.get("skill_name", ""),
            description=row.get("description", ""),
            risk_level=row.get("risk_level", "低"),
            permission_level=row.get("permission_level", "普通"),
            applicable_scenes=list(row.get("applicable_scenes") or []),
            raw=row,
        )

    # ---- invoke ----------------------------------------------------
    def invoke(self, skill_id: str, args: dict[str, Any], ctx: Any | None = None) -> dict[str, Any]:
        rows = self.storage.list_records(
            TableName.SKILL_CATALOG, where={"skill_id": skill_id}, limit=1
        )
        if not rows:
            raise KeyError(f"unknown skill_id: {skill_id}")
        skill = rows[0]

        decision = self._policy_decide(skill, ctx)
        if decision == "block":
            raise PermissionError(f"skill blocked by policy: {skill_id}")

        tool_name = skill.get("required_tools") or ["noop"]
        if isinstance(tool_name, list):
            tool_name = tool_name[0] if tool_name else "noop"
        client = self.mcp.get(tool_name) or self.mcp["noop"]
        t0 = time.time()
        result = client(tool_name, args)
        return {
            "skill_id": skill_id,
            "skill_name": skill.get("skill_name"),
            "result": result,
            "tool": tool_name,
            "latency_ms": int((time.time() - t0) * 1000),
            "policy_decision": decision,
        }

    def _policy_decide(self, skill: dict[str, Any], ctx: Any | None) -> str:
        risk = (skill.get("risk_level") or "低")
        if risk == "高":
            return "ask"
        if risk == "中" and skill.get("permission_level") == "管理员":
            return "ask"
        return "allow"


# ---- mock MCP clients ----------------------------------------------
def _default_mcp_clients() -> dict[str, Callable[[str, dict], Any]]:
    """Demo-friendly mock implementations so `hub.invoke` works offline."""

    def noop(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"ok": True, "args_echo": args}

    def read_logs(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"lines": 5, "snippet": f"[mock logs for {args.get('service','')}]"}

    def query_metrics(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"cpu": "95%+", "rt_p99_ms": 3120, "qps": 820}

    def query_monitoring(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"db_connections_active": 200, "db_connections_max": 200}

    def notify_oncall(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"sent": True, "channel": args.get("channel", "default")}

    def send_feishu_card(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"card_id": f"card_{int(time.time()*1000)}"}

    def get_system_architecture(_tool: str, args: dict[str, Any]) -> dict[str, Any]:
        return {"services": ["order", "payment", "user"], "topology": "fan-out"}

    return {
        "noop": noop,
        "read_logs": read_logs,
        "query_metrics": query_metrics,
        "query_monitoring": query_monitoring,
        "notify_oncall": notify_oncall,
        "send_feishu_card": send_feishu_card,
        "get_system_architecture": get_system_architecture,
    }
