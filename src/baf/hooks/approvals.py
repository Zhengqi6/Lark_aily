"""Approval Registry — async hook pattern (Claude Code AsyncHookRegistry).

The Fix Agent (or any destructive agent) requests approval before
applying its plan. The registry:

  1. Writes a row to PendingApprovals with status=pending
  2. (Optionally) sends a Feishu approval card
  3. Returns immediately so the Orchestrator can keep streaming
  4. A background poll task (or `baf approve <case>` CLI) flips the row
     to approved/rejected/timeout — the Orchestrator picks it up on its
     next tick.

For the offline demo we expose `auto_approve(card_id)` so the
end-to-end pipeline can run without manual intervention.
"""
from __future__ import annotations

import time
import uuid
from dataclasses import dataclass
from typing import Any

from ..storage.backend import StorageBackend, TableName

DEFAULT_TIMEOUT_SECONDS = 300  # 5 minutes


@dataclass
class ApprovalEvent:
    card_id: str
    status: str            # "approved" | "rejected" | "timeout" | "pending"
    note: str = ""

    def is_terminal(self) -> bool:
        return self.status in {"approved", "rejected", "timeout"}


class ApprovalRegistry:
    """Synchronous (and async-friendly) approval coordinator.

    Methods are sync to keep them callable from both the sync MVP
    orchestrator and the async stream orchestrator. They never block on
    network I/O — Feishu calls are best-effort (mocked when absent).
    """

    def __init__(self, storage: StorageBackend, feishu_client: Any | None = None,
                 timeout_seconds: int = DEFAULT_TIMEOUT_SECONDS):
        self.storage = storage
        self.feishu = feishu_client
        self.timeout_seconds = timeout_seconds

    # ---- request ---------------------------------------------------
    def request(
        self,
        case_id: str,
        agent_run_id: str,
        payload: dict[str, Any],
    ) -> str:
        """Send an approval card and persist a pending row.

        Returns the synthesized `card_id` (which is also a row key).
        """
        card_id = self._send_card(payload) or f"card_{uuid.uuid4().hex[:10]}"
        self.storage.create_record(
            TableName.PENDING_APPROVALS,
            {
                "card_id": card_id,
                "case_id": case_id,
                "agent_run_id": agent_run_id,
                "status": "pending",
                "payload": payload,
                "requested_at": time.time(),
                "expires_at": time.time() + self.timeout_seconds,
            },
        )
        return card_id

    def _send_card(self, payload: dict[str, Any]) -> str | None:
        """Send a Feishu approval card. Returns card_id or None for mocked path."""
        if self.feishu is None:
            return None
        try:
            return self.feishu.send_approval_card(payload)  # type: ignore[no-any-return]
        except Exception:
            return None

    # ---- decide ----------------------------------------------------
    def decide(self, card_id: str, status: str, note: str = "") -> None:
        rows = self.storage.list_records(
            TableName.PENDING_APPROVALS, where={"card_id": card_id}
        )
        if not rows:
            raise KeyError(f"no pending approval for card_id={card_id}")
        row = rows[0]
        self.storage.update_record(
            TableName.PENDING_APPROVALS,
            row["_id"],
            {
                "status": status,
                "decision_note": note,
                "decided_at": time.time(),
            },
        )

    # convenience for demo / tests
    def auto_approve(self, card_id: str, note: str = "auto-approved (demo)") -> None:
        self.decide(card_id, "approved", note)

    # ---- poll ------------------------------------------------------
    def poll(self, case_id: str | None = None) -> list[ApprovalEvent]:
        """Scan pending rows; return terminal events (timeout flips happen here).

        The Orchestrator calls this between ticks.
        """
        where = {"status": "pending"}
        if case_id is not None:
            where["case_id"] = case_id
        rows = self.storage.list_records(TableName.PENDING_APPROVALS, where=where, limit=500)
        events: list[ApprovalEvent] = []
        now = time.time()
        for r in rows:
            if (r.get("expires_at") or 0) and r["expires_at"] < now:
                # auto-timeout
                self.storage.update_record(
                    TableName.PENDING_APPROVALS,
                    r["_id"],
                    {"status": "timeout", "decided_at": now},
                )
                events.append(ApprovalEvent(card_id=r.get("card_id"), status="timeout",
                                            note="超过 5 分钟未审批"))
        # also surface already-decided rows that haven't been consumed yet
        decided = self.storage.list_records(
            TableName.PENDING_APPROVALS,
            where={"case_id": case_id} if case_id else None,
            limit=500,
        )
        for r in decided:
            if r.get("status") in {"approved", "rejected", "timeout"}:
                events.append(ApprovalEvent(
                    card_id=r.get("card_id"),
                    status=r.get("status"),
                    note=r.get("decision_note") or "",
                ))
        return events

    def get(self, card_id: str) -> dict[str, Any] | None:
        rows = self.storage.list_records(
            TableName.PENDING_APPROVALS, where={"card_id": card_id}
        )
        return rows[0] if rows else None

    def wait_for(self, card_id: str, *, poll_interval: float = 0.5,
                 max_wait: float | None = None) -> ApprovalEvent:
        """Block until an approval reaches a terminal status (or times out).

        Used by the sync Orchestrator. Async callers should use
        `await asyncio.to_thread(registry.wait_for, ...)`.
        """
        deadline = time.time() + (max_wait or self.timeout_seconds + 5)
        while time.time() < deadline:
            row = self.get(card_id)
            if not row:
                raise KeyError(card_id)
            status = row.get("status")
            if status in {"approved", "rejected", "timeout"}:
                return ApprovalEvent(
                    card_id=card_id, status=status,
                    note=row.get("decision_note") or "",
                )
            # auto-flip on local timeout
            if (row.get("expires_at") or 0) < time.time():
                self.storage.update_record(
                    TableName.PENDING_APPROVALS, row["_id"],
                    {"status": "timeout", "decided_at": time.time()},
                )
                return ApprovalEvent(card_id=card_id, status="timeout", note="local timeout")
            time.sleep(poll_interval)
        return ApprovalEvent(card_id=card_id, status="timeout", note="wait_for hard deadline")
