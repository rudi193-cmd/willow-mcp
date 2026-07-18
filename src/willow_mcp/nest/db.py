"""
nest-seed/db.py — portable SQLite Nest schema.

Mirrors the Squirrel fragment model but with no Postgres/fleet dependency.
The DB file is the Nest. One file per person or project. Canonical — never
mutated by consumers; apps write sidecars and fleet promotes.

Tables:
  sources      — original files ingested (path, hash, OCR method, status)
  fragments    — classified pieces extracted from sources
  nest_meta    — one-row DB identity record
"""
from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path
from typing import Any

FRAGMENT_TYPES = frozenset({
    "person", "date", "location", "event",
    "document", "photo", "note", "receipt", "secret", "unknown",
})
CONFIDENCE_LEVELS = frozenset({"confirmed", "likely", "uncertain", "speculative"})

SCHEMA = """
CREATE TABLE IF NOT EXISTS nest_meta (
    id          INTEGER PRIMARY KEY CHECK (id = 1),
    owner       TEXT NOT NULL,
    created_at  TEXT NOT NULL DEFAULT (datetime('now')),
    description TEXT
);

CREATE TABLE IF NOT EXISTS sources (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    path        TEXT NOT NULL,
    filename    TEXT NOT NULL,
    file_hash   TEXT NOT NULL UNIQUE,
    mime_hint   TEXT,
    ocr_method  TEXT,
    char_count  INTEGER DEFAULT 0,
    status      TEXT NOT NULL DEFAULT 'pending'
                CHECK (status IN ('pending','extracted','failed','skipped')),
    error       TEXT,
    ingested_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS fragments (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    source_id       INTEGER NOT NULL REFERENCES sources(id),
    fragment_type   TEXT NOT NULL,
    content         TEXT NOT NULL,
    label           TEXT,
    confidence      TEXT NOT NULL DEFAULT 'uncertain',
    date_ref        TEXT,
    created_at      TEXT DEFAULT (datetime('now')),
    kb_atom_id      TEXT
);

CREATE INDEX IF NOT EXISTS idx_fragments_source   ON fragments (source_id);
CREATE INDEX IF NOT EXISTS idx_fragments_type     ON fragments (fragment_type);
CREATE INDEX IF NOT EXISTS idx_sources_status     ON sources (status);
"""


def open_db(path: str | Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def init_meta(conn: sqlite3.Connection, owner: str, description: str = "") -> None:
    conn.execute(
        "INSERT OR IGNORE INTO nest_meta (id, owner, description) VALUES (1, ?, ?)",
        (owner, description),
    )
    conn.commit()


def file_hash(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()[:16]


def add_source(conn: sqlite3.Connection, path: Path, mime_hint: str = "") -> int:
    fhash = file_hash(path)
    cur = conn.execute("SELECT id FROM sources WHERE file_hash = ?", (fhash,))
    row = cur.fetchone()
    if row:
        return row["id"]
    cur = conn.execute(
        "INSERT INTO sources (path, filename, file_hash, mime_hint) VALUES (?, ?, ?, ?)",
        (str(path), path.name, fhash, mime_hint),
    )
    conn.commit()
    return cur.lastrowid


def update_source_status(conn: sqlite3.Connection, source_id: int,
                         status: str, ocr_method: str = "",
                         char_count: int = 0, error: str = "") -> None:
    conn.execute(
        "UPDATE sources SET status=?, ocr_method=?, char_count=?, error=? WHERE id=?",
        (status, ocr_method, char_count, error, source_id),
    )
    conn.commit()


def add_fragment(conn: sqlite3.Connection, *, source_id: int,
                 fragment_type: str, content: str, label: str = "",
                 confidence: str = "uncertain", date_ref: str = "",
                 kb_atom_id: str = "") -> int:
    if fragment_type not in FRAGMENT_TYPES:
        fragment_type = "unknown"
    if confidence not in CONFIDENCE_LEVELS:
        confidence = "uncertain"
    cur = conn.execute(
        """INSERT INTO fragments
           (source_id, fragment_type, content, label, confidence, date_ref, kb_atom_id)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (source_id, fragment_type, content, label, confidence, date_ref, kb_atom_id),
    )
    conn.commit()
    return cur.lastrowid


def stats(conn: sqlite3.Connection) -> dict[str, Any]:
    sources = conn.execute("SELECT status, COUNT(*) n FROM sources GROUP BY status").fetchall()
    frags = conn.execute("SELECT fragment_type, COUNT(*) n FROM fragments GROUP BY fragment_type").fetchall()
    return {
        "sources": {r["status"]: r["n"] for r in sources},
        "fragments": {r["fragment_type"]: r["n"] for r in frags},
    }
