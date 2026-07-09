"""willow_mcp/core.py — record_lessons(): distill a journal into a ring.

Takes a SQLite journal — any journal, any schema, including one that has
waited twenty years on a forgotten development machine — and reads it the
way `schema_profile` reads an unfamiliar table: introspect, don't assume.
It finds the table that holds the writing, counts the entries, dates the
range if the schema offers a date, tallies which themes the entries kept
returning to, and grows exactly one ring in the grove
(`the_grove.add_ring`) carrying the one sentence worth keeping.

The source is opened strictly read-only (`mode=ro`): a journal handed to
this function is being remembered, not edited. All failure is fail-soft —
a missing or unreadable journal returns `{"error": ...}` and grows no ring,
because a ring must never record a lesson that wasn't actually learned.
"""
from __future__ import annotations

import logging
import sqlite3
from pathlib import Path
from typing import Optional

from . import the_grove

logger = logging.getLogger(__name__)

# The default lesson. It is the seed's own thesis, and the reason a journal
# is worth distilling at all: what younger-you lacked was never the idea.
SEED_LESSON = "The infrastructure arrives. The seed was always there."

# What a journal tends to circle. Callers with different weather may pass
# their own {theme: (fragment, ...)} lexicon; matching is case-insensitive
# substring, so "isolat" catches isolated/isolating/isolation.
DEFAULT_THEMES: dict[str, tuple[str, ...]] = {
    "loneliness": ("lonely", "loneliness", "alone", "isolat"),
    "systems": ("system", "database", "schema", "server", "network", "script", "code"),
    "what should persist": ("remember", "persist", "keep", "save", "forget", "backup"),
    "shame": ("shame", "ashamed", "embarrass", "regret"),
    "joy": ("joy", "happy", "laugh", "delight", "love"),
}

_TEXT_AFFINITY = ("CHAR", "TEXT", "CLOB")
_DATE_NAME_HINTS = ("date", "created", "updated", "timestamp", "time", "when", "day")


def _text_and_date_columns(conn, table: str) -> tuple[list[str], Optional[str]]:
    text_cols, date_col = [], None
    for _cid, name, ctype, *_ in conn.execute(f'PRAGMA table_info("{table}")'):
        upper = (ctype or "").upper()
        lowered = name.lower()
        if any(h in lowered for h in _DATE_NAME_HINTS) and date_col is None:
            date_col = name
        elif upper == "" or any(a in upper for a in _TEXT_AFFINITY):
            text_cols.append(name)
    return text_cols, date_col


def _journal_table(conn) -> Optional[tuple[str, list[str], Optional[str]]]:
    """The table that holds the writing: the one with at least one text
    column and the most rows. Introspected, never assumed — a 2004 schema
    owes the present nothing."""
    tables = [r[0] for r in conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    best = None
    for table in tables:
        text_cols, date_col = _text_and_date_columns(conn, table)
        if not text_cols:
            continue
        count = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
        if best is None or count > best[0]:
            best = (count, table, text_cols, date_col)
    if best is None:
        return None
    return best[1], best[2], best[3]


def record_lessons(journal_path: str, themes: Optional[dict] = None,
                   lesson: Optional[str] = None) -> dict:
    """Distill `journal_path` and grow one ring. Returns what was learned:
    {source, table, entries, range, themes, lesson, ring, depth} — or
    {"error": ...} having grown nothing."""
    path = Path(journal_path).expanduser()
    if not path.is_file():
        return {"error": "not_found", "source": str(path)}

    logger.info("Initializing lesson record...")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            found = _journal_table(conn)
            if found is None:
                return {"error": "no_text_table", "source": str(path)}
            table, text_cols, date_col = found

            entries = conn.execute(f'SELECT COUNT(*) FROM "{table}"').fetchone()[0]
            date_range = None
            if date_col:
                lo, hi = conn.execute(
                    f'SELECT MIN("{date_col}"), MAX("{date_col}") FROM "{table}"'
                ).fetchone()
                if lo is not None:
                    date_range = [str(lo), str(hi)]

            logger.info("Extracting themes...")
            lexicon = themes if themes is not None else DEFAULT_THEMES
            counts = {theme: 0 for theme in lexicon}
            joined = " || ".join(f'COALESCE("{c}", \'\')' for c in text_cols)
            for (body,) in conn.execute(f'SELECT {joined} FROM "{table}"'):
                lowered = (body or "").lower()
                for theme, fragments in lexicon.items():
                    if any(f in lowered for f in fragments):
                        counts[theme] += 1
        finally:
            conn.close()
    except sqlite3.Error:
        return {"error": "unreadable", "source": str(path)}

    recorded = (lesson or SEED_LESSON).strip()
    ring = the_grove.add_ring(recorded, source=path.name, themes=counts)
    logger.info("record_lessons() complete.")
    logger.info("Lesson recorded: %s", recorded)
    return {
        "source": str(path),
        "table": table,
        "entries": entries,
        "range": date_range,
        "themes": counts,
        "lesson": recorded,
        "ring": ring,
        "depth": the_grove.depth(),
    }
