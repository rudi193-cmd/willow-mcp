"""willow_mcp/grove.py — Grove workspace-messaging data-access layer.

Ported from the canonical Grove implementation:
  - safe-app-willow-grove/grove_db.py     (channels, messages, flags, bus)
  - safe-app-willow-grove/grove_reader.py (agents, fleet rows, inbox bundle,
    human-required queue)

Those two files are the read-only reference this module was ported from —
never modify that repo to satisfy willow-mcp. The SQL and the shapes returned
match the canonical functions; what changed is the connection underneath:

  * Canonical `grove_db.py` owns a `psycopg2.pool.ThreadedConnectionPool` of
    its own, with each caller checking a connection out and back in.
  * willow-mcp already has exactly one Postgres access path — `db.get_pg()`,
    a single shared **autocommit** connection reused by every tool in the
    server. This module is written against that connection instead of
    importing `grove_db`/`grove_reader` over PYTHONPATH, so willow-mcp stays a
    self-contained, independently distributable package (no sibling-repo
    dependency at import time or at run time).

Two consequences of sharing one autocommit connection with every other tool:

  1. **No `SET search_path`.** Canonical code sets `search_path = grove,
     public` once per checked-out connection. Doing that on willow-mcp's
     shared connection would leak into every *other* tool's unqualified
     queries against `public` for the lifetime of the process. Every query
     here schema-qualifies instead: `grove.channels`, `grove.messages`,
     `grove.message_flags`, `public.human_required_queue`.
  2. **No explicit commit/rollback.** Autocommit means every statement is its
     own transaction; there is nothing to roll back after an error, and
     nothing to commit after a write — matching how the rest of willow-mcp
     already uses `db.get_pg()` (see server.py's `knowledge_ingest`,
     `task_submit`, etc.).

DB-NAME TRAP (see README / DEVELOPER docs): `grove.*` and
`public.human_required_queue` live in the fleet's `willow_20` database, but
`db.get_pg()` defaults `WILLOW_PG_DB=willow`. Every function below fails
closed with `GroveUnavailable` naming the fix
(`export WILLOW_PG_DB=willow_20`) instead of letting a bare
`psycopg2.errors.UndefinedTable` traceback reach an MCP caller.

Deliberately NOT ported from the canonical source:
  * Schema bootstrap (`init_schema` / `_bootstrap_schema`). willow-mcp does
    not self-bootstrap any other Postgres table it reads (knowledge, tasks,
    fleet.*) — those schemas are managed outside this repo, and grove's is
    too (by safe-app-willow-grove's own `grove_db.init_schema`). Creating
    schema/tables from a read path would also fight the DB-name trap: a
    misconfigured `WILLOW_PG_DB` would silently create an *empty* grove
    schema in the wrong database instead of surfacing the clear error above.
  * The FRANK tamper-evident ledger append on every send
    (`_frank_ledger_append` in the canonical `grove_db.send_message`).
    willow-mcp has its own, separately-gated FRANK surface
    (`frank_append`/`frank_read`/`frank_verify`, `frank_head_anchor.py`) with
    its own project/event-type conventions; wiring grove sends into it is a
    separate decision left to that surface, not assumed here.
  * The `pg_trgm` GIN index auto-creation in `_ensure_mention_index`. It is a
    performance optimization for `ILIKE '%@handle%'` mention search, not a
    correctness requirement — `grove_inbox`/mentions still work, just doing a
    full scan, without it. Auto-running `CREATE EXTENSION`/`CREATE INDEX`
    from a *read* tool the first time anyone polls their inbox is a
    surprising DDL side effect on a shared fleet database; left to the
    canonical dashboard (or an operator migration) instead.
  * Column-fallback compatibility branches (e.g. `grove_agents`' fallback
    query for a pre-bus-protocol schema without `bus_type`). The bus
    envelope columns have been part of `grove_db.init_schema` unconditionally
    since the bus protocol shipped; a fresh port does not need to carry
    forward that migration-era compatibility shim.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Optional

import psycopg2.errors

SCHEMA = "grove"

VALID_FLAGS = frozenset({"needs-reply", "starred", "read", "urgent", "resolved"})

# Same set the canonical `grove_db.py` validates against, and the same set
# `grove.messages.message_type`'s CHECK constraint enforces at the DB layer —
# checked here too so an invalid value raises a clear ValueError instead of a
# raw psycopg2 CheckViolation. No `grove_tools.py` write tool exposes
# `message_type` as a parameter today (every call site uses the "text"
# default), so this is defense in depth against a future caller, not a fix
# for an observed bad value.
VALID_MESSAGE_TYPES = frozenset({"text", "system", "file_share", "reaction"})

BUS_TYPES = frozenset({
    "COMMAND",    # instruct an agent to do something
    "RESPONSE",   # reply to a COMMAND
    "EVENT",      # something happened (fire and forget)
    "INTERRUPT",  # act immediately, preempt normal flow
    "HEARTBEAT",  # I am alive
    "ACK",        # I received and understood your message
    "DATA",       # bulk payload, routed to Kart/DMA layer
    "SYNC",       # synchronise state between agents
})
BUS_BROADCAST = "__all__"   # sentinel: message is addressed to every agent

_MSG_COLUMNS = (
    "id, channel_id, sender, content, message_type, reply_to_id, "
    "to_agent, bus_type, priority, correlation_id, ttl, "
    "willow_indexed_at, created_at, is_deleted"
)
_m_cols = ", ".join(f"m.{c.strip()}" for c in _MSG_COLUMNS.split(","))


class GroveUnavailable(Exception):
    """Grove's Postgres surface could not be reached.

    Raised in place of letting a bare `psycopg2.errors.UndefinedTable`
    escape to a caller — `.detail` carries the operator-actionable message
    (the WILLOW_PG_DB=willow_20 fix), which tool bodies fold into their
    normal `{"error": ...}` / `[{"error": ...}]` return shape rather than an
    exception traceback.
    """

    def __init__(self, detail: str):
        self.detail = detail
        super().__init__(detail)


def _translate_missing_table(exc: Exception) -> "GroveUnavailable":
    return GroveUnavailable(
        "Grove's tables were not found in the connected Postgres database "
        f"({exc}). Grove lives in the fleet's `willow_20` database, not "
        "willow-mcp's default `willow` database — set "
        "WILLOW_PG_DB=willow_20 in the willow-mcp server's environment "
        "and restart it."
    )


def jsonify(value: Any) -> Any:
    """Recursively coerce non-JSON-safe Postgres types to JSON-safe ones.

    datetime/date -> ISO string; Decimal (psycopg2 returns NUMERIC as
    Decimal) -> float; set/frozenset -> list. Dicts and sequences recurse.
    Every public function below returns raw driver types (a caller that
    wants Python objects, e.g. for further filtering, gets them); tool
    bodies in grove_tools.py call this before handing a result back over MCP.
    """
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, dict):
        return {k: jsonify(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [jsonify(v) for v in value]
    return value


# ---------------------------------------------------------------------------
# Channels
# ---------------------------------------------------------------------------

def normalize_channel_name(name: str) -> str:
    """Fold a channel name to the form stored in grove.channels.

    Senders reach us with Discord-style '#fleet' or padded ' fleet ' while
    the stored row is 'fleet'.
    """
    return (name or "").strip().lstrip("#").strip()


def find_channel_in(channels: list[dict], name: str) -> Optional[dict]:
    """Locate a channel by name in an already-fetched list, folding variants."""
    target = normalize_channel_name(name)
    if not target:
        return None
    return next(
        (c for c in channels if normalize_channel_name(c["name"]) == target),
        None,
    )


def list_channels(pg, include_archived: bool = False) -> list[dict]:
    cur = pg.cursor()
    try:
        cols = "id, name, channel_type, description, created_at, updated_at, is_archived, agent_name"
        # `cols` is the fixed literal above, never caller input; nothing here is
        # interpolated from a request. Same pattern as db.py's Store.search.
        if include_archived:
            cur.execute(f"SELECT {cols} FROM grove.channels ORDER BY name")  # nosec B608
        else:
            cur.execute(f"SELECT {cols} FROM grove.channels WHERE is_archived = FALSE ORDER BY name")  # nosec B608
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def create_channel(pg, *, name: str, channel_type: str = "group",
                    description: Optional[str] = None) -> dict:
    name = normalize_channel_name(name)
    if not name:
        raise ValueError("channel name must not be empty after normalization")
    cur = pg.cursor()
    try:
        cur.execute(
            """
            INSERT INTO grove.channels (name, channel_type, description)
            VALUES (%s, %s, %s)
            RETURNING id, name, channel_type, description, created_at, updated_at, is_archived
            """,
            (name, channel_type, description),
        )
        row = cur.fetchone()
        colnames = [d[0] for d in cur.description]
        return dict(zip(colnames, row))
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Messages
# ---------------------------------------------------------------------------

def send_message(pg, *, channel_id: int, sender: str, content: str,
                  message_type: str = "text", reply_to_id: Optional[int] = None) -> dict:
    if message_type not in VALID_MESSAGE_TYPES:
        raise ValueError(f"message_type must be one of {sorted(VALID_MESSAGE_TYPES)}")
    cur = pg.cursor()
    try:
        if reply_to_id is not None:
            cur.execute(
                "SELECT id, channel_id FROM grove.messages WHERE id = %s AND is_deleted = 0",  # nosec B608 - every value is a bound param
                (reply_to_id,),
            )
            target = cur.fetchone()
            if not target:
                return {"error": "reply_target_not_found", "reply_to_id": reply_to_id}
            target_channel_id = target[1]
            if target_channel_id != channel_id:
                return {
                    "error": "cross_channel_reply",
                    "reply_to_id": reply_to_id,
                    "target_channel_id": target_channel_id,
                    "message_channel_id": channel_id,
                }
        cur.execute(
            f"""
            INSERT INTO grove.messages (channel_id, sender, content, message_type, reply_to_id)
            VALUES (%s, %s, %s, %s, %s)
            RETURNING {_MSG_COLUMNS}
            """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
            (channel_id, sender, content, message_type, reply_to_id),
        )
        row = cur.fetchone()
        colnames = [d[0] for d in cur.description]
        return dict(zip(colnames, row))
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_message(pg, message_id: int) -> Optional[dict]:
    """A single (non-deleted) message by id, or None."""
    cur = pg.cursor()
    try:
        cur.execute(
            f"SELECT {_MSG_COLUMNS} FROM grove.messages WHERE id = %s AND is_deleted = 0",  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
            (message_id,),
        )
        row = cur.fetchone()
        if not row:
            return None
        colnames = [d[0] for d in cur.description]
        return dict(zip(colnames, row))
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_history(pg, channel_id: int, limit: int = 100,
                 before_id: Optional[int] = None, since_id: Optional[int] = None) -> list[dict]:
    """Top-level messages (no replies).

    before_id: newest-first pagination (go backward).
    since_id:  forward polling — id > since_id, oldest first.
    """
    cur = pg.cursor()
    try:
        if since_id is not None:
            cur.execute(
                f"""
                SELECT {_m_cols}, COALESCE(rc.reply_count, 0) AS reply_count
                FROM grove.messages m
                LEFT JOIN (
                    SELECT reply_to_id, COUNT(*) AS reply_count
                    FROM grove.messages
                    WHERE reply_to_id IS NOT NULL AND is_deleted = 0
                    GROUP BY reply_to_id
                ) rc ON rc.reply_to_id = m.id
                WHERE m.channel_id = %s AND m.reply_to_id IS NULL AND m.is_deleted = 0 AND m.id > %s
                ORDER BY m.id ASC LIMIT %s
                """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
                (channel_id, since_id, limit),
            )
        elif before_id:
            cur.execute(
                f"""
                SELECT {_m_cols}, COALESCE(rc.reply_count, 0) AS reply_count
                FROM grove.messages m
                LEFT JOIN (
                    SELECT reply_to_id, COUNT(*) AS reply_count
                    FROM grove.messages
                    WHERE reply_to_id IS NOT NULL AND is_deleted = 0
                    GROUP BY reply_to_id
                ) rc ON rc.reply_to_id = m.id
                WHERE m.channel_id = %s AND m.reply_to_id IS NULL AND m.is_deleted = 0 AND m.id < %s
                ORDER BY m.created_at DESC LIMIT %s
                """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
                (channel_id, before_id, limit),
            )
        else:
            cur.execute(
                f"""
                SELECT {_m_cols}, COALESCE(rc.reply_count, 0) AS reply_count
                FROM grove.messages m
                LEFT JOIN (
                    SELECT reply_to_id, COUNT(*) AS reply_count
                    FROM grove.messages
                    WHERE reply_to_id IS NOT NULL AND is_deleted = 0
                    GROUP BY reply_to_id
                ) rc ON rc.reply_to_id = m.id
                WHERE m.channel_id = %s AND m.reply_to_id IS NULL AND m.is_deleted = 0
                ORDER BY m.created_at DESC LIMIT %s
                """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
                (channel_id, limit),
            )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_thread(pg, parent_id: int, *, max_depth: int = 50) -> list[dict]:
    """All replies in a thread (recursive), oldest first, with depth."""
    cur = pg.cursor()
    try:
        cur.execute(
            f"""
            WITH RECURSIVE thread AS (
                SELECT {_MSG_COLUMNS}, 1 AS depth
                FROM grove.messages
                WHERE reply_to_id = %s AND is_deleted = 0
                UNION ALL
                SELECT {_m_cols}, t.depth + 1
                FROM grove.messages m
                JOIN thread t ON m.reply_to_id = t.id
                WHERE m.is_deleted = 0 AND t.depth < %s
            )
            SELECT * FROM thread
            ORDER BY created_at ASC
            """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal; all values are bound params
            (parent_id, max_depth),
        )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_thread_root(pg, message_id: int, *, max_hops: int = 50) -> Optional[dict]:
    """Walk reply_to_id upward to find the thread root message."""
    cur = pg.cursor()
    try:
        cur.execute(
            f"""
            WITH RECURSIVE chain AS (
                SELECT {_MSG_COLUMNS}, 0 AS hops
                FROM grove.messages
                WHERE id = %s AND is_deleted = 0
                UNION ALL
                SELECT {_m_cols}, c.hops + 1
                FROM grove.messages m
                JOIN chain c ON c.reply_to_id = m.id
                WHERE m.is_deleted = 0 AND c.hops < %s
            )
            SELECT * FROM chain
            ORDER BY hops DESC
            LIMIT 1
            """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal; all values are bound params
            (message_id, max_hops),
        )
        row = cur.fetchone()
        if not row:
            return None
        colnames = [d[0] for d in cur.description]
        return dict(zip(colnames, row))
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def search_messages(pg, query: str, channel_id: Optional[int] = None) -> list[dict]:
    cur = pg.cursor()
    try:
        if channel_id is not None:
            cur.execute(
                f"""
                SELECT {_MSG_COLUMNS} FROM grove.messages
                WHERE content ILIKE %s AND channel_id = %s AND is_deleted = 0
                ORDER BY created_at DESC LIMIT 100
                """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
                (f"%{query}%", channel_id),
            )
        else:
            cur.execute(
                f"""
                SELECT {_MSG_COLUMNS} FROM grove.messages
                WHERE content ILIKE %s AND is_deleted = 0
                ORDER BY created_at DESC LIMIT 100
                """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
                (f"%{query}%",),
            )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------

def set_flag(pg, *, message_id: int, sender: str, flag: str) -> bool:
    if flag not in VALID_FLAGS:
        raise ValueError(f"flag must be one of {sorted(VALID_FLAGS)}")
    cur = pg.cursor()
    try:
        cur.execute(
            """
            INSERT INTO grove.message_flags (message_id, sender, flag)
            VALUES (%s, %s, %s) ON CONFLICT (message_id, sender, flag) DO NOTHING
            """,
            (message_id, sender, flag),
        )
        return cur.rowcount > 0
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def clear_flag(pg, *, message_id: int, sender: str, flag: str) -> bool:
    cur = pg.cursor()
    try:
        cur.execute(
            "DELETE FROM grove.message_flags WHERE message_id = %s AND sender = %s AND flag = %s",
            (message_id, sender, flag),
        )
        return cur.rowcount > 0
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_flags(pg, message_id: int) -> list[dict]:
    cur = pg.cursor()
    try:
        cur.execute(
            "SELECT sender, flag, created_at FROM grove.message_flags "
            "WHERE message_id = %s ORDER BY created_at",
            (message_id,),
        )
        return [{"sender": r[0], "flag": r[1], "created_at": r[2]} for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def get_flagged(pg, flag: str, channel_id: Optional[int] = None, limit: int = 50) -> list[dict]:
    cur = pg.cursor()
    try:
        cols = ", ".join(f"m.{c}" for c in _MSG_COLUMNS.split(", "))
        if channel_id is not None:
            cur.execute(
                f"""
                SELECT {cols} FROM grove.messages m
                JOIN grove.message_flags f ON f.message_id = m.id
                WHERE f.flag = %s AND m.channel_id = %s AND m.is_deleted = 0
                ORDER BY m.created_at DESC LIMIT %s
                """,  # nosec B608 - cols is built from the fixed _MSG_COLUMNS literal, not input; every value is a bound param
                (flag, channel_id, limit),
            )
        else:
            cur.execute(
                f"""
                SELECT {cols} FROM grove.messages m
                JOIN grove.message_flags f ON f.message_id = m.id
                WHERE f.flag = %s AND m.is_deleted = 0
                ORDER BY m.created_at DESC LIMIT %s
                """,  # nosec B608 - cols is built from the fixed _MSG_COLUMNS literal, not input; every value is a bound param
                (flag, limit),
            )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Bus
# ---------------------------------------------------------------------------

def bus_send(pg, *, channel_id: int, sender: str, content: str,
             to_agent: str = BUS_BROADCAST, bus_type: str = "EVENT",
             priority: int = 3, correlation_id: Optional[str] = None,
             ttl: Optional[int] = None) -> dict:
    if bus_type not in BUS_TYPES:
        raise ValueError(f"bus_type must be one of {sorted(BUS_TYPES)}")
    cur = pg.cursor()
    try:
        cur.execute(
            """
            INSERT INTO grove.messages
                (channel_id, sender, content, message_type, to_agent, bus_type, priority, correlation_id, ttl)
            VALUES (%s, %s, %s, 'text', %s, %s, %s, %s, %s)
            RETURNING id, channel_id, sender, content, to_agent, bus_type, priority,
                      correlation_id, ttl, created_at
            """,
            (channel_id, sender, content, to_agent, bus_type, priority, correlation_id, ttl),
        )
        row = cur.fetchone()
        colnames = [d[0] for d in cur.description]
        return dict(zip(colnames, row))
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def bus_receive(pg, agent: str, since_id: int = 0, limit: int = 50) -> list[dict]:
    cur = pg.cursor()
    try:
        cur.execute(
            f"""
            SELECT {_MSG_COLUMNS} FROM grove.messages
            WHERE (
                LOWER(TRIM(COALESCE(to_agent, ''))) = LOWER(TRIM(%s))
                OR to_agent = %s
              )
              AND is_deleted = 0
              AND id > %s
              AND (ttl IS NULL OR created_at + (ttl || ' seconds')::interval > NOW())
            ORDER BY priority ASC, id ASC
            LIMIT %s
            """,  # nosec B608 - _MSG_COLUMNS is a fixed module-level literal, not input; every value is a bound param
            (agent, BUS_BROADCAST, since_id, limit),
        )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Fleet awareness (ported from grove_reader.py)
# ---------------------------------------------------------------------------

def agents(pg) -> list[dict]:
    """Agents from HEARTBEAT bus messages, most recent first.

    Each entry: {sender, last_seen_at: datetime, age_secs: int}
    """
    cur = pg.cursor()
    try:
        cur.execute(
            """
            SELECT sender, MAX(created_at) AS last_seen
            FROM grove.messages
            WHERE bus_type = 'HEARTBEAT' AND is_deleted = 0
            GROUP BY sender
            ORDER BY last_seen DESC
            LIMIT 20
            """
        )
        rows = cur.fetchall()
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()
    now = datetime.now(timezone.utc)
    out = []
    for sender, last_seen in rows:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        out.append({
            "sender": sender,
            "last_seen_at": last_seen,
            "age_secs": int((now - last_seen).total_seconds()),
        })
    return out


def _ui_state(age_secs: Optional[int], hb_content: Optional[str]) -> str:
    if hb_content and hb_content.lstrip().startswith("[AGENT_VIEW] status=blocked"):
        return "blocked"
    if age_secs is None:
        return "unknown"
    if age_secs < 120:
        return "running"
    if age_secs < 900:
        return "idle"
    return "stale"


def agent_fleet_rows(pg, limit: int = 50) -> list[dict]:
    """Fleet rows: sender, last_seen_at, age_secs, ui_state, peek, blocked,
    reply_to_message_id, correlation_id. Two round-trips (canonical §7)."""
    cur = pg.cursor()
    try:
        cur.execute(
            """
            SELECT m.sender, m.created_at, m.content
            FROM grove.messages m
            JOIN (
                SELECT sender, MAX(id) AS hb_id
                FROM grove.messages
                WHERE bus_type = 'HEARTBEAT' AND is_deleted = 0
                GROUP BY sender
            ) latest ON m.id = latest.hb_id
            ORDER BY m.created_at DESC
            LIMIT %s
            """,
            (limit,),
        )
        hb_rows = cur.fetchall()

        now = datetime.now(timezone.utc)
        senders = [r[0] for r in hb_rows]

        peek_by_sender: dict = {}
        if senders:
            cur.execute(
                """
                SELECT DISTINCT ON (m.sender)
                    m.sender, m.id, m.content, m.correlation_id,
                    (mf.message_id IS NOT NULL) AS needs_reply
                FROM grove.messages m
                LEFT JOIN grove.message_flags mf
                       ON mf.message_id = m.id AND mf.flag = 'needs-reply'
                WHERE m.sender = ANY(%s)
                  AND m.bus_type != 'HEARTBEAT'
                  AND m.is_deleted = 0
                ORDER BY m.sender, m.id DESC
                """,
                (senders,),
            )
            for row in cur.fetchall():
                peek_by_sender[row[0]] = {
                    "peek_id": row[1],
                    "peek": (row[2] or "")[:200],
                    "correlation_id": row[3],
                    "needs_reply": bool(row[4]),
                }
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()

    rows = []
    for sender, last_seen, hb_content in hb_rows:
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        age_secs = int((now - last_seen).total_seconds())
        peek_data = peek_by_sender.get(sender, {})
        needs_reply = peek_data.get("needs_reply", False)
        state = _ui_state(age_secs, hb_content)
        if needs_reply and state != "blocked":
            state = "blocked"
        rows.append({
            "sender": sender,
            "last_seen_at": last_seen,
            "age_secs": age_secs,
            "ui_state": state,
            "peek": peek_data.get("peek", ""),
            "blocked": needs_reply or state == "blocked",
            "reply_to_message_id": peek_data.get("peek_id") if needs_reply else None,
            "correlation_id": peek_data.get("correlation_id"),
        })
    return rows


def human_required_queue(pg, *, limit: int = 30, open_only: bool = True) -> list[dict]:
    """Items from public.human_required_queue — work that pauses automation
    until a human acts. Priority-first, then newest.

    Each entry: {id, kind, title, summary, status, priority, source_agent,
                 source_ref, assignee, created_at}
    """
    cur = pg.cursor()
    try:
        where = "WHERE status = 'open'" if open_only else ""
        cur.execute(
            f"""
            SELECT id, kind, title, summary, status, priority,
                   source_agent, source_ref, assignee, created_at
            FROM public.human_required_queue
            {where}
            ORDER BY
                CASE priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1
                              WHEN 'normal' THEN 2 WHEN 'low' THEN 3 ELSE 4 END,
                created_at DESC
            LIMIT %s
            """,  # nosec B608 - `where` is one of two fixed literals selected by a bool, never input; limit is a bound param
            (limit,),
        )
        colnames = [d[0] for d in cur.description]
        return [dict(zip(colnames, r)) for r in cur.fetchall()]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


# ---------------------------------------------------------------------------
# Fleet inbox bundle (ported from grove_reader.py's grove_inbox_bundle et al.)
# ---------------------------------------------------------------------------

def _mention_handles(agent: str) -> list[str]:
    """Handles to match @-mentions against: the agent itself, plus 'all' so
    @all broadcasts surface. (Canonical also folds in GROVE_DESK_MENTIONS env
    extras for the dashboard; that is a local-operator display preference,
    not part of an MCP tool's contract, so it is not ported here.)"""
    handles: list[str] = []
    seen: set[str] = set()

    def _add(raw: str) -> None:
        h = (raw or "").strip().lstrip("@")
        if not h:
            return
        k = h.lower()
        if k in seen:
            return
        seen.add(k)
        handles.append(h)

    _add(agent)
    _add("all")
    return handles


def mentions_for_handles(pg, handles: list[str], limit: int = 20) -> list[dict]:
    """Recent messages matching @<handle> for any handle (ILIKE substring,
    case-folded). Each entry: {id, channel, sender, content}."""
    clean: list[str] = []
    seen: set[str] = set()
    for raw in handles:
        h = (raw or "").strip().lstrip("@")
        if not h:
            continue
        k = h.lower()
        if k in seen:
            continue
        seen.add(k)
        clean.append(h)
    if not clean:
        return []
    cur = pg.cursor()
    try:
        # `clean` is a caller-supplied list of *handles*, never raw SQL — the
        # placeholder count mirrors its length, every value is still a bound
        # param (same pattern as db.py's Store.search: fixed literal repeated
        # N times, values parameterized). nosec B608.
        placeholders = " OR ".join(["m.content ILIKE %s"] * len(clean))
        params: list = [f"%@{h}%" for h in clean]
        params.append(limit)
        cur.execute(
            f"""
            SELECT m.id, c.name, m.sender, m.content
            FROM grove.messages m
            JOIN grove.channels c ON c.id = m.channel_id
            WHERE ({placeholders})
              AND m.is_deleted = 0
              AND c.is_archived = FALSE
            ORDER BY m.id DESC
            LIMIT %s
            """,  # nosec B608 - placeholders is a fixed literal repeated N times per comment above; every value is a bound param
            params,
        )
        return [
            {"id": r[0], "channel": r[1], "sender": r[2], "content": r[3]}
            for r in cur.fetchall()
        ]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def messages_bus_addressed_to(pg, recipient: str, *, since_id: int = 0,
                               limit: int = 40) -> list[dict]:
    """Messages bus-routed *directly* to recipient (to_agent matches,
    case-insensitive). Drops HEARTBEAT/ACK noise; excludes '__all__'
    broadcasts (those surface via mentions/history instead)."""
    r = (recipient or "").strip()
    if not r:
        return []
    cur = pg.cursor()
    try:
        cur.execute(
            """
            SELECT m.id, c.name, m.sender, m.content
            FROM grove.messages m
            JOIN grove.channels c ON c.id = m.channel_id
            WHERE m.is_deleted = 0
              AND c.is_archived = FALSE
              AND m.id > %s
              AND LOWER(TRIM(COALESCE(m.to_agent, ''))) = LOWER(TRIM(%s))
              AND LOWER(TRIM(COALESCE(m.to_agent, ''))) <> '__all__'
              AND COALESCE(m.bus_type, '') NOT IN ('HEARTBEAT', 'ACK')
            ORDER BY m.id DESC
            LIMIT %s
            """,
            (since_id, r, limit),
        )
        return [
            {"id": row[0], "channel": row[1], "sender": row[2], "content": row[3]}
            for row in cur.fetchall()
        ]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def own_channel_since(pg, channel_name: str, *, since_id: int = 0,
                       limit: int = 80) -> list[dict]:
    """Every text message in the agent-dedicated channel (canonical rule 1:
    lowercased sender identity, e.g. Auto -> #auto). Skips HEARTBEAT bus
    noise."""
    ch = (channel_name or "").strip()
    if not ch:
        return []
    cur = pg.cursor()
    try:
        cur.execute(
            """
            SELECT m.id, c.name, m.sender, m.content
              FROM grove.messages m
              JOIN grove.channels c ON c.id = m.channel_id
             WHERE LOWER(TRIM(c.name)) = LOWER(TRIM(%s))
               AND m.is_deleted = 0
               AND c.is_archived = FALSE
               AND m.id > %s
               AND COALESCE(m.bus_type, '') NOT IN ('HEARTBEAT', 'ACK')
             ORDER BY m.id DESC
             LIMIT %s
            """,
            (ch, since_id, limit),
        )
        return [
            {"id": row[0], "channel": row[1], "sender": row[2], "content": row[3]}
            for row in cur.fetchall()
        ]
    except psycopg2.errors.UndefinedTable as e:
        raise _translate_missing_table(e) from e
    finally:
        cur.close()


def merge_attention_messages(*row_groups: list[dict], limit: int = 20) -> list[dict]:
    """Dedupe-by-id descending merge for the inbox bundle. Pure Python, no DB."""
    seen: set[int] = set()
    out: list[dict] = []
    merged: list[dict] = []
    for grp in row_groups:
        merged.extend(grp or [])
    for row in sorted(merged, key=lambda r: -int(r["id"])):
        mid = int(row["id"])
        if mid in seen:
            continue
        seen.add(mid)
        out.append(row)
        if len(out) >= limit:
            break
    return out


def inbox_bundle(pg, agent: str, *, since_id: int = 0, mention_limit: int = 60,
                  bus_limit: int = 60, merge_limit: int = 35) -> list[dict]:
    """Unified pull: @mentions + bus to_agent + dedicated #<agent> inbox."""
    who = (agent or "").strip()
    if not who:
        raise ValueError("agent is required")
    handles = _mention_handles(who)
    inbox_name = who.lower().replace(" ", "-")
    mention_rows = mentions_for_handles(pg, handles, limit=mention_limit)
    bus_rows = messages_bus_addressed_to(pg, who, since_id=since_id, limit=bus_limit)
    own_rows = own_channel_since(pg, inbox_name, since_id=since_id, limit=mention_limit)
    filtered_mentions = [m for m in mention_rows if int(m["id"]) > since_id]
    return merge_attention_messages(filtered_mentions, bus_rows, own_rows, limit=merge_limit)
