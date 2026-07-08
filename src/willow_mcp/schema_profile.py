"""willow_mcp/schema_profile.py — introspect a host table, map it to canonical
fields, and persist the result as a reviewable artifact.

Implements docs/design/schema-adaptation.md §3.1-§3.4: introspection +
heuristic mapping for the read path (§9 step 2), and confirm() for the
write-path gate (§9 step 3) — a table's mapping must be explicitly
confirmed (optionally with human-supplied column overrides) before any
write tool may use it.

Design principles this module exists to satisfy (see doc §2):
  1. Discover, don't assume — introspect() is the only source of column
     truth; no caller may embed a column name that wasn't confirmed present.
  2. Map to canonical concepts, with visible confidence — every mapped field
     carries a tier (exact / alias / unmapped); never hidden from the caller.
  4. The mapping is an artifact, not a black box — persisted as plain JSON,
     diffable and editable, confirmed mappings win over fresh heuristics.
  5. Every inference is logged implicitly by being written to that artifact
     with a discovered_at timestamp; a dedicated audit log is future work
     (§5, not this pass).
"""
import hashlib
import json
import os
import re
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1

# Static-but-extensible alias dictionary (§7 open question, resolved as
# "static built-in list" for the first pass — a per-deployment override file
# is cheap to add later if a host schema needs a name this list doesn't
# anticipate).
CANONICAL_ALIASES: dict[str, tuple[str, ...]] = {
    "source": ("source_type", "origin", "origin_ref"),
    "content": ("content", "body", "text"),
    "tags": ("tags", "labels"),
    "task_id": ("id",),
}

# Column data types that must be cast to text before use in an ILIKE
# predicate — jsonb/json columns don't support the ~~ operator directly.
_TEXT_CAST_TYPES = frozenset({"jsonb", "json"})

_COLLECTION_SAFE_RE = re.compile(r"^[A-Za-z0-9_\-]{1,128}$")


@dataclass(frozen=True)
class ColumnInfo:
    name: str
    data_type: str


def introspect(conn, table: str) -> list[ColumnInfo]:
    """Query information_schema for a table's real columns. Empty list means
    the table doesn't exist (or is empty of columns, which is equivalent for
    our purposes) — callers must treat that as table_not_found, not as
    "every field unmapped."."""
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_schema = 'public' AND table_name = %s "
            "ORDER BY ordinal_position",
            (table,),
        )
        rows = cur.fetchall()
    finally:
        cur.close()
    return [ColumnInfo(name=r[0], data_type=r[1]) for r in rows]


def propose_mapping(columns: list[ColumnInfo], canonical_fields: list[str]) -> dict:
    """Heuristic pass: exact name match -> known alias -> unmapped.

    Returns {field: {"column": str|None, "tier": "exact"|"alias"|"unmapped",
    "confidence": float, "data_type": str|None}}. Pure function of its
    arguments — same columns + same canonical_fields always produce the same
    mapping, so re-running it on an unconfirmed artifact is safe.
    """
    by_name = {c.name: c for c in columns}
    mapping: dict = {}
    for field in canonical_fields:
        if field in by_name:
            col = by_name[field]
            mapping[field] = {
                "column": col.name, "tier": "exact",
                "confidence": 1.0, "data_type": col.data_type,
            }
            continue
        found = None
        for alias in CANONICAL_ALIASES.get(field, ()):
            if alias in by_name:
                found = by_name[alias]
                break
        if found is not None:
            mapping[field] = {
                "column": found.name, "tier": "alias",
                "confidence": 0.9, "data_type": found.data_type,
            }
        else:
            mapping[field] = {
                "column": None, "tier": "unmapped",
                "confidence": 0.0, "data_type": None,
            }
    return mapping


def db_fingerprint(conn) -> str:
    """Stable identifier for 'this database' — host + dbname only, never
    connection-string secrets (user/password), so it's safe to use as a
    filename and to persist in a reviewable artifact."""
    dsn = conn.get_dsn_parameters()
    key = f"{dsn.get('host') or 'local'}:{dsn.get('dbname', '')}"
    return hashlib.sha256(key.encode()).hexdigest()[:16]


def _apps_root() -> Path:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))
    return Path(os.environ.get("WILLOW_MCP_APPS_ROOT", home / "mcp_apps"))


def _validate_table(table: str) -> str:
    if not table or not _COLLECTION_SAFE_RE.match(table):
        raise ValueError(f"invalid table name: {table!r}")
    return table


def mapping_path(app_id: str, fingerprint: str, table: str) -> Path:
    _validate_table(table)
    root = _apps_root() / app_id / "schema_maps"
    root.mkdir(parents=True, exist_ok=True)
    return root / f"{fingerprint}__{table}.json"


def _write_json_atomic(path: Path, record: dict) -> None:
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record, indent=2))
    os.replace(tmp, path)


def load_mapping(app_id: str, fingerprint: str, table: str) -> Optional[dict]:
    path = mapping_path(app_id, fingerprint, table)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def save_mapping(app_id: str, fingerprint: str, table: str, record: dict) -> None:
    _write_json_atomic(mapping_path(app_id, fingerprint, table), record)


def resolve(conn, app_id: str, table: str, canonical_fields: list[str]) -> dict:
    """Top-level entry point: discover-or-load a mapping for (db, table).

    Returns the mapping artifact dict, always including "fields", "confirmed",
    and "schema_version". On a table that doesn't exist, returns
    {"error": "table_not_found", "table": table} instead — callers must check
    for "error" before touching "fields".

    A confirmed mapping is re-validated against a fresh introspection every
    call: if any confirmed field's column no longer exists, confirmed is
    downgraded to false and "schema_drift": true is set (doc §4) rather than
    building SQL against columns that may no longer mean what a human
    confirmed them to mean. An unconfirmed mapping is simply recomputed —
    propose_mapping is pure, so this only changes the result when the real
    columns changed, which is exactly when it should.
    """
    columns = introspect(conn, table)
    if not columns:
        return {"error": "table_not_found", "table": table}

    fingerprint = db_fingerprint(conn)
    existing = load_mapping(app_id, fingerprint, table)
    fresh_fields = propose_mapping(columns, canonical_fields)

    if existing and existing.get("confirmed"):
        by_name = {c.name for c in columns}
        drifted = any(
            f.get("column") and f["column"] not in by_name
            for f in existing.get("fields", {}).values()
        )
        if drifted:
            existing["confirmed"] = False
            existing["schema_drift"] = True
            existing["fields"] = fresh_fields
            save_mapping(app_id, fingerprint, table, existing)
        return existing

    record = {
        "schema_version": SCHEMA_VERSION,
        "database": fingerprint,
        "table": table,
        "discovered_at": datetime.now(timezone.utc).isoformat(),
        "confirmed": False,
        "fields": fresh_fields,
    }
    save_mapping(app_id, fingerprint, table, record)
    return record


def confirm(
    conn, app_id: str, table: str, canonical_fields: list[str],
    overrides: Optional[dict] = None,
) -> dict:
    """Confirm a table's mapping, unlocking write tools for it (§3.4).

    Starts from whatever's already on disk (preserving any prior human
    corrections), or a fresh heuristic proposal if nothing was ever
    computed. `overrides` lets a human correct individual
    canonical-field -> real-column assignments before confirming — pass
    `{"field": "real_column"}` to point a field at a specific column, or
    `{"field": None}` to explicitly mark it unmapped (DROP). An override
    column must exist in a *fresh* introspection or the whole call is
    refused — a confirmed mapping must never point at a column that isn't
    actually there (doc §2 principle 3: writes may not guess).

    Returns the saved, confirmed mapping record, or {"error":
    "table_not_found"|"unknown_field"|"override_invalid", ...}.
    """
    columns = introspect(conn, table)
    if not columns:
        return {"error": "table_not_found", "table": table}
    by_name = {c.name: c for c in columns}

    fingerprint = db_fingerprint(conn)
    existing = load_mapping(app_id, fingerprint, table)
    base_fields = (existing or {}).get("fields") or propose_mapping(columns, canonical_fields)
    fields = {f: dict(v) for f, v in base_fields.items()}

    if overrides:
        for field, col in overrides.items():
            if field not in canonical_fields:
                return {"error": "unknown_field", "field": field, "table": table}
            if col is None:
                fields[field] = {"column": None, "tier": "unmapped", "confidence": 0.0, "data_type": None}
            elif col not in by_name:
                return {"error": "override_invalid", "field": field, "column": col, "table": table}
            else:
                fields[field] = {
                    "column": col, "tier": "confirmed_override",
                    "confidence": 1.0, "data_type": by_name[col].data_type,
                }

    record = {
        "schema_version": SCHEMA_VERSION,
        "database": fingerprint,
        "table": table,
        "discovered_at": (existing or {}).get("discovered_at") or datetime.now(timezone.utc).isoformat(),
        "confirmed": True,
        "confirmed_at": datetime.now(timezone.utc).isoformat(),
        "fields": fields,
    }
    save_mapping(app_id, fingerprint, table, record)
    return record


def cast_for_ilike(field_mapping: dict) -> str:
    """Return the column reference to use in an ILIKE predicate, casting to
    text first if the real column is jsonb/json (doc §6.1-style type
    wrinkle, applies to §3 too: knowledge.content is jsonb, not text)."""
    col = field_mapping["column"]
    if field_mapping.get("data_type") in _TEXT_CAST_TYPES:
        return f'"{col}"::text'
    return f'"{col}"'
