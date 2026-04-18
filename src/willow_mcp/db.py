"""Database connections — Postgres (Unix socket) and SQLite store."""

import json
import os
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


class Store:
    """SQLite-backed key/value store. One database per collection."""

    def __init__(self, store_root: Optional[str] = None):
        self.root = Path(store_root or os.environ.get(
            "WILLOW_STORE_ROOT",
            Path.home() / ".willow" / "store"
        ))
        self.root.mkdir(parents=True, exist_ok=True)
        self._conns: dict[str, sqlite3.Connection] = {}
        self._lock = threading.Lock()

    def _conn(self, collection: str) -> sqlite3.Connection:
        with self._lock:
            if collection not in self._conns:
                db_path = self.root / f"{collection}.db"
                conn = sqlite3.connect(str(db_path), check_same_thread=False)
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS atoms (
                        id TEXT PRIMARY KEY,
                        domain TEXT NOT NULL DEFAULT 'default',
                        content TEXT NOT NULL,
                        meta TEXT DEFAULT '{}',
                        created TEXT NOT NULL,
                        updated TEXT NOT NULL
                    )
                """)
                conn.execute("CREATE INDEX IF NOT EXISTS idx_domain ON atoms(domain)")
                conn.commit()
                self._conns[collection] = conn
            return self._conns[collection]

    def put(self, collection: str, content: str, domain: str = "default",
            atom_id: Optional[str] = None, meta: Optional[dict] = None) -> str:
        atom_id = atom_id or str(uuid.uuid4())[:8].upper()
        now = datetime.now(timezone.utc).isoformat()
        conn = self._conn(collection)
        conn.execute(
            "INSERT OR REPLACE INTO atoms (id, domain, content, meta, created, updated) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (atom_id, domain, content, json.dumps(meta or {}), now, now)
        )
        conn.commit()
        return atom_id

    def get(self, collection: str, atom_id: str) -> Optional[dict]:
        conn = self._conn(collection)
        row = conn.execute(
            "SELECT id, domain, content, meta, created, updated FROM atoms WHERE id = ?",
            (atom_id,)
        ).fetchone()
        if not row:
            return None
        return {"id": row[0], "domain": row[1], "content": row[2],
                "meta": json.loads(row[3]), "created": row[4], "updated": row[5]}

    def list_atoms(self, collection: str, domain: Optional[str] = None, limit: int = 20) -> list[dict]:
        conn = self._conn(collection)
        if domain:
            rows = conn.execute(
                "SELECT id, domain, content, meta, created FROM atoms WHERE domain = ? "
                "ORDER BY created DESC LIMIT ?", (domain, limit)
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT id, domain, content, meta, created FROM atoms "
                "ORDER BY created DESC LIMIT ?", (limit,)
            ).fetchall()
        return [{"id": r[0], "domain": r[1], "content": r[2],
                 "meta": json.loads(r[3]), "created": r[4]} for r in rows]

    def search(self, collection: str, query: str, limit: int = 10) -> list[dict]:
        conn = self._conn(collection)
        rows = conn.execute(
            "SELECT id, domain, content, meta, created FROM atoms "
            "WHERE content LIKE ? ORDER BY created DESC LIMIT ?",
            (f"%{query}%", limit)
        ).fetchall()
        return [{"id": r[0], "domain": r[1], "content": r[2],
                 "meta": json.loads(r[3]), "created": r[4]} for r in rows]

    def delete(self, collection: str, atom_id: str) -> bool:
        conn = self._conn(collection)
        cur = conn.execute("DELETE FROM atoms WHERE id = ?", (atom_id,))
        conn.commit()
        return cur.rowcount > 0

    def search_all(self, query: str, limit: int = 10) -> list[dict]:
        results = []
        for db_path in sorted(self.root.glob("*.db")):
            collection = db_path.stem
            for item in self.search(collection, query, limit):
                item["collection"] = collection
                results.append(item)
        return results[:limit]
