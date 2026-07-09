"""Database — Postgres (Unix socket) and SQLite store aligned with willow-2.0 WillowStore."""

import json
import os
import re
import sqlite3
import threading
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg2
import psycopg2.extras

_pg_conn = None
_pg_lock = threading.Lock()

# server.py's _sanitize() already rejects a path-traversal collection before
# a tool call reaches Store — this is a second, independent check inside
# Store itself, so a future direct caller (a script, a test, a new code
# path) can't reach the filesystem with an unsanitized collection name just
# because it bypassed the MCP guard pipeline.
_COLLECTION_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


def _validate_collection(collection: str) -> str:
    if not collection or not _COLLECTION_RE.match(collection):
        raise ValueError(f"invalid collection name: {collection!r}")
    return collection


def collection_in_scope(collection: str, scope: Optional[list]) -> bool:
    """True if `collection` is allowed under a manifest's optional `store_scope`.

    `scope=None` means unrestricted *within this install's own store* — unscoped
    apps keep seeing everything they always could; this is opt-in isolation, not
    a retroactive lockdown. Which store that is depends on WILLOW_STORE_ROOT: an
    install may share the wider fleet's store or hold its own, and
    `diagnostic_summary`'s `severance` check reports which. Sharing is a default,
    not a design commitment — an unscoped grant's blast radius is whatever store
    this process resolved. A pattern ending in "*" matches by prefix (e.g.
    "myapp_*"); otherwise it's an exact match. Empty list means "no collections"
    (deny-all), not "unrestricted" — callers that want unrestricted must omit the
    field entirely.
    """
    if scope is None:
        return True
    for pattern in scope:
        if pattern.endswith("*"):
            if collection.startswith(pattern[:-1]):
                return True
        elif collection == pattern:
            return True
    return False


def get_pg() -> Optional[psycopg2.extensions.connection]:
    """Return a Postgres connection via Unix socket, or None."""
    global _pg_conn
    with _pg_lock:
        try:
            if _pg_conn is None or _pg_conn.closed:
                _pg_conn = psycopg2.connect(
                    dbname=os.environ.get("WILLOW_PG_DB", "willow"),
                    user=os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
                )
                _pg_conn.autocommit = True
            _pg_conn.cursor().execute("SELECT 1")
            return _pg_conn
        except Exception:
            _pg_conn = None
            return None


_SCHEMA = """
CREATE TABLE IF NOT EXISTS records (
    id         TEXT PRIMARY KEY,
    data       TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deviation  REAL NOT NULL DEFAULT 0.0,
    action     TEXT NOT NULL DEFAULT 'work_quiet',
    deleted    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_deleted ON records(deleted);
"""

def _action_for(deviation: float) -> str:
    if deviation >= 1.571:
        return "stop"
    if deviation >= 0.785:
        return "flag"
    return "work_quiet"


class Store:
    """SQLite-backed store aligned with willow-2.0 WillowStore.

    Schema: one records table per collection, data stored as JSON blob.
    Shares WILLOW_STORE_ROOT with willow-2.0 when set to the same path.
    """

    def __init__(self, store_root: Optional[str] = None):
        self.root = Path(store_root or os.environ.get(
            "WILLOW_STORE_ROOT",
            Path.home() / ".willow" / "store"
        ))
        self.root.mkdir(parents=True, exist_ok=True)
        self._conns: dict[str, sqlite3.Connection] = {}
        # RLock (not Lock): _conn() is called from within an already-locked
        # method body below, and a plain Lock would deadlock on re-entry.
        self._lock = threading.RLock()

    def _conn(self, collection: str) -> sqlite3.Connection:
        _validate_collection(collection)
        with self._lock:
            if collection not in self._conns:
                db_path = self.root / collection / "store.db"
                db_path.parent.mkdir(parents=True, exist_ok=True)
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                conn.executescript(_SCHEMA)
                conn.commit()
                self._conns[collection] = conn
            return self._conns[collection]

    def put(self, collection: str, record: dict, record_id: str = None,
            deviation: float = 0.0) -> tuple[str, str]:
        rid = record_id or str(uuid.uuid4())[:8].lower()
        action = _action_for(deviation)
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._conn(collection)
            conn.execute(
                "INSERT OR REPLACE INTO records (id, data, created_at, updated_at, deviation, action) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (rid, json.dumps(record), now, now, deviation, action)
            )
            conn.commit()
        return rid, action

    def get(self, collection: str, record_id: str) -> Optional[dict]:
        with self._lock:
            conn = self._conn(collection)
            row = conn.execute(
                "SELECT data, created_at, updated_at, deviation, action "
                "FROM records WHERE id = ? AND deleted = 0",
                (record_id,)
            ).fetchone()
        if not row:
            return None
        record = json.loads(row[0])
        record["_id"] = record_id
        record["_created"] = row[1]
        record["_updated"] = row[2]
        record["_deviation"] = row[3]
        record["_action"] = row[4]
        return record

    def all(self, collection: str) -> list[dict]:
        with self._lock:
            conn = self._conn(collection)
            rows = conn.execute(
                "SELECT id, data, created_at, updated_at, deviation, action "
                "FROM records WHERE deleted = 0 ORDER BY created_at"
            ).fetchall()
        results = []
        for row in rows:
            record = json.loads(row[1])
            record["_id"] = row[0]
            record["_created"] = row[2]
            record["_updated"] = row[3]
            record["_deviation"] = row[4]
            record["_action"] = row[5]
            results.append(record)
        return results

    def update(self, collection: str, record_id: str, record: dict,
               deviation: float = 0.0) -> Optional[str]:
        now = datetime.now(timezone.utc).isoformat()
        action = _action_for(deviation)
        with self._lock:
            conn = self._conn(collection)
            result = conn.execute(
                "UPDATE records SET data = ?, updated_at = ?, deviation = ?, action = ? "
                "WHERE id = ? AND deleted = 0",
                (json.dumps(record), now, deviation, action, record_id)
            )
            conn.commit()
        return record_id if result.rowcount > 0 else None

    def search(self, collection: str, query: str) -> list[dict]:
        """Multi-keyword AND search (all tokens must appear in JSON data)."""
        tokens = query.split()
        if not tokens:
            return []
        conditions = " AND ".join(["data LIKE ?"] * len(tokens))
        params = tuple(f"%{t}%" for t in tokens)
        with self._lock:
            conn = self._conn(collection)
            rows = conn.execute(
                f"SELECT id, data, deviation, action FROM records "
                f"WHERE deleted = 0 AND {conditions}",
                params
            ).fetchall()
        results = []
        for row in rows:
            record = json.loads(row[1])
            record["_id"] = row[0]
            record["_deviation"] = row[2]
            record["_action"] = row[3]
            results.append(record)
        return results

    def search_all(self, query: str, scope: Optional[list] = None) -> list[dict]:
        """Search every collection, or only those matching `scope` if given.

        `scope=None` preserves today's default: search everything under this
        store root — which is the wider fleet's store unless WILLOW_STORE_ROOT
        says otherwise, so the reach of an unscoped search is whatever store this
        process resolved (`diagnostic_summary`'s `severance` check). Pass a
        manifest's `store_scope` list to confine an app's search_all to the
        same collections its other store_* calls are restricted to.
        """
        results = []
        for db_file in sorted(self.root.rglob("store.db")):
            col = str(db_file.parent.relative_to(self.root))
            if col.startswith("."):
                continue
            try:
                _validate_collection(col)
            except ValueError:
                # An on-disk directory that predates _validate_collection or
                # was created outside this class — skip it rather than let
                # one bad entry crash the whole search_all call.
                continue
            if not collection_in_scope(col, scope):
                continue
            for record in self.search(col, query):
                record["_collection"] = col
                results.append(record)
        return results

    def delete(self, collection: str, record_id: str) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        with self._lock:
            conn = self._conn(collection)
            result = conn.execute(
                "UPDATE records SET deleted = 1, updated_at = ? WHERE id = ? AND deleted = 0",
                (now, record_id)
            )
            conn.commit()
        return result.rowcount > 0
