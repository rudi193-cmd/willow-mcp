"""The Nest interchange contract — willow-mcp side (safe-app-store #17).

willow-mcp's Nest engine (``willow_mcp.nest``) and the standalone ``nest-seed``
app in safe-app-store are twins on one SQLite schema. The MCP tools
``nest_status`` / ``nest_digest`` / ``nest_promote`` read a ``seed.db`` that may
have been built by *either* engine — including one nest-seed produced on a
machine that never had the fleet installed. The risk is silent drift: a column
added on one side that breaks cross-consumption with no error.

nest-seed pins this same contract in its own ``tests/test_nest_interchange.py``.
This is the mirror on the fleet side, so a drift on *either* engine turns a
test red instead of a promotion silently losing data. The constant below is the
canonical interchange shape; keep the two copies identical.
"""
from __future__ import annotations

from willow_mcp.nest import db as nest_db


# The frozen interchange contract — must stay byte-identical to nest-seed's copy.
CANONICAL_COLUMNS = {
    "nest_meta": {"id", "owner", "description", "created_at"},
    "sources": {
        "id", "path", "filename", "file_hash", "mime_hint", "status",
        "ocr_method", "char_count", "error", "ingested_at",
    },
    "fragments": {
        "id", "source_id", "fragment_type", "label", "content", "confidence",
        "date_ref", "kb_atom_id", "created_at",
    },
}


def _columns(conn, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}


def test_fleet_nest_schema_matches_interchange_contract(tmp_path):
    conn = nest_db.open_db(tmp_path / "seed.db")
    try:
        for table, expected in CANONICAL_COLUMNS.items():
            actual = _columns(conn, table)
            assert actual == expected, (
                f"willow-mcp nest table {table!r} drifted from the nest-seed "
                f"interchange contract.\n  only in willow-mcp: {sorted(actual - expected)}"
                f"\n  missing from willow-mcp: {sorted(expected - actual)}"
            )
    finally:
        conn.close()
