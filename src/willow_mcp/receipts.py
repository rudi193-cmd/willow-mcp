"""willow_mcp/receipts.py — append-only audit trail for every tool call.

Phase 4c. One row per tool call regardless of outcome (ok / denied /
rate_limited / error). Dedicated SQLite connection — never shares the
Store's connections, so a busy receipt log can't stall a store_* call
or vice versa.
"""
import os
import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from . import paths

_SCHEMA = """
CREATE TABLE IF NOT EXISTS receipts (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        TEXT NOT NULL,
    app_id    TEXT NOT NULL,
    tool      TEXT NOT NULL,
    outcome   TEXT NOT NULL,
    detail    TEXT
);
CREATE INDEX IF NOT EXISTS idx_receipts_ts     ON receipts(ts DESC);
CREATE INDEX IF NOT EXISTS idx_receipts_app_id ON receipts(app_id);
"""


class ReceiptLog:
    """Append-only SQLite log of every tool call."""

    def __init__(self, db_path: Optional[str] = None):
        # Default under $WILLOW_HOME so the audit trail stays inside the
        # sovereign box (the data-vault boundary). Explicit db_path wins, then
        # the WILLOW_MCP_RECEIPT_DB override, then $WILLOW_HOME/mcp_receipt.db.
        self.path = Path(
            db_path
            or os.environ.get("WILLOW_MCP_RECEIPT_DB")
            or (paths.willow_home() / "mcp_receipt.db")
        )
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(str(self.path), check_same_thread=False)
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def record(self, app_id: str, tool: str, outcome: str, detail: Optional[str] = None) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        with self._lock:
            self._conn.execute(
                "INSERT INTO receipts (ts, app_id, tool, outcome, detail) VALUES (?, ?, ?, ?, ?)",
                (ts, app_id, tool, outcome, detail)
            )
            self._conn.commit()

    def since(self, app_id: str, ts_iso: str, outcome: Optional[str] = None,
              limit: int = 2000) -> list[dict]:
        """This app_id's receipts at or after `ts_iso`, oldest first.

        The session-reconciliation feed (willow-gate seam H3): `tools_used` must
        come from the receipt log, or a declare-vs-did diff silently passes on
        out-of-band use. ISO-8601 UTC timestamps sort lexicographically in
        chronological order, so a string `ts >= ?` bound is a correct time window.
        Optionally narrow to a single `outcome` (e.g. only calls that actually
        ran). Scoped to one app_id, like tail() — never another identity's calls.
        """
        limit = max(1, min(int(limit), 10000))
        q = ("SELECT ts, tool, outcome, detail FROM receipts "
             "WHERE app_id = ? AND ts >= ?")
        params: list = [app_id, ts_iso]
        if outcome is not None:
            q += " AND outcome = ?"
            params.append(outcome)
        q += " ORDER BY id ASC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(q, tuple(params)).fetchall()
        return [{"ts": r[0], "tool": r[1], "outcome": r[2], "detail": r[3]} for r in rows]

    def tail(self, app_id: str, limit: int = 20) -> list[dict]:
        """Return this app_id's own most-recent receipts, newest first.

        Scoped to the single app_id on purpose — the audit trail is a
        self-legibility feature ('what did I just do?'), never a way to read
        another identity's calls. A caller only ever sees its own rows.
        """
        limit = max(1, min(int(limit), 200))
        with self._lock:
            rows = self._conn.execute(
                "SELECT ts, tool, outcome, detail FROM receipts "
                "WHERE app_id = ? ORDER BY id DESC LIMIT ?",
                (app_id, limit),
            ).fetchall()
        return [{"ts": r[0], "tool": r[1], "outcome": r[2], "detail": r[3]} for r in rows]
