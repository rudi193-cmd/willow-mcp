"""Tests for willow_mcp.grove — the Grove data-access layer.

Exercised against a fake psycopg2-shaped connection that records executed SQL
and plays back pre-programmed (columns, rows, rowcount) tuples in call order —
same style as tests/test_task_queue.py's _FakePg, adapted for grove.py's
`cur.description` / `cur.fetchone()` / `cur.fetchall()` usage. No live
Postgres is touched.
"""
from datetime import datetime, timezone

import psycopg2.errors
import pytest

from willow_mcp import grove


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn
        self.description = None
        self.rowcount = 0
        self._rows = []

    def execute(self, sql, params=None):
        self._conn.calls.append((sql, params))
        cols, rows, rowcount = self._conn._pop_response()
        self.description = [(c,) for c in cols] if cols is not None else None
        self._rows = list(rows or [])
        self.rowcount = rowcount

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None

    def close(self):
        pass


class _FakePg:
    def __init__(self, responses):
        # responses: list of (cols, rows, rowcount) tuples, consumed in the
        # order the code under test issues cursor.execute() calls.
        self._responses = list(responses)
        self.calls = []

    def cursor(self):
        return _FakeCursor(self)

    def _pop_response(self):
        if not self._responses:
            return (None, [], 0)
        return self._responses.pop(0)


def _now():
    return datetime(2026, 8, 18, 12, 0, 0, tzinfo=timezone.utc)


# ── jsonify ──────────────────────────────────────────────────────────────────

def test_jsonify_converts_datetime_and_decimal_and_recurses():
    from decimal import Decimal

    payload = {
        "when": _now(),
        "amount": Decimal("3.5"),
        "nested": [{"ts": _now()}, {"n": Decimal("1")}],
        "plain": "unchanged",
    }
    out = grove.jsonify(payload)
    assert out["when"] == _now().isoformat()
    assert out["amount"] == 3.5
    assert isinstance(out["amount"], float)
    assert out["nested"][0]["ts"] == _now().isoformat()
    assert out["nested"][1]["n"] == 1.0
    assert out["plain"] == "unchanged"


# ── channel helpers (pure Python) ───────────────────────────────────────────

def test_normalize_channel_name_strips_hash_and_whitespace():
    assert grove.normalize_channel_name("  #fleet  ") == "fleet"
    assert grove.normalize_channel_name("fleet") == "fleet"
    assert grove.normalize_channel_name("") == ""


def test_find_channel_in_matches_normalized_variants():
    channels = [{"id": 1, "name": "fleet"}, {"id": 2, "name": "general"}]
    assert grove.find_channel_in(channels, "#fleet")["id"] == 1
    assert grove.find_channel_in(channels, "  general ")["id"] == 2
    assert grove.find_channel_in(channels, "nope") is None


# ── reads return rows, datetimes intact at the data layer ──────────────────

def test_list_channels_returns_rows():
    cols = ["id", "name", "channel_type", "description", "created_at",
            "updated_at", "is_archived", "agent_name"]
    rows = [(1, "general", "group", "General chat", _now(), _now(), False, None)]
    pg = _FakePg([(cols, rows, 0)])
    result = grove.list_channels(pg)
    assert len(result) == 1
    assert result[0]["name"] == "general"
    assert result[0]["channel_type"] == "group"
    # data layer hands back native datetimes — jsonify is the tool layer's job
    assert result[0]["created_at"] == _now()


def test_get_history_since_id_orders_ascending():
    cols = grove._MSG_COLUMNS.split(", ")
    rows = [
        (5, 1, "hanuman", "hi", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0),
    ]
    pg = _FakePg([(cols, rows, 0)])
    result = grove.get_history(pg, channel_id=1, since_id=4)
    assert result[0]["id"] == 5
    assert result[0]["sender"] == "hanuman"
    sql, params = pg.calls[0]
    assert "id > %s" in sql
    assert params == (1, 4, 100)


def test_agents_converts_heartbeat_rows_and_computes_age():
    rows = [("hanuman", _now())]
    pg = _FakePg([(None, rows, 0)])
    result = grove.agents(pg)
    assert result[0]["sender"] == "hanuman"
    assert result[0]["last_seen_at"] == _now()
    assert isinstance(result[0]["age_secs"], int)


def test_human_required_queue_reads_public_table():
    cols = ["id", "kind", "title", "summary", "status", "priority",
            "source_agent", "source_ref", "assignee", "created_at"]
    rows = [(1, "review", "check this", "", "open", "high", "loki", "", "", _now())]
    pg = _FakePg([(cols, rows, 0)])
    result = grove.human_required_queue(pg, limit=10)
    assert result[0]["title"] == "check this"
    sql, params = pg.calls[0]
    assert "public.human_required_queue" in sql


# ── writes issue the right INSERT ───────────────────────────────────────────

def test_send_message_inserts_with_given_sender():
    cols = grove._MSG_COLUMNS.split(", ")
    row = (9, 1, "hanuman", "hello fleet", "text", None, "__all__", "EVENT", 3, None, None, None, _now(), 0)
    pg = _FakePg([(cols, [row], 0)])
    msg = grove.send_message(pg, channel_id=1, sender="hanuman", content="hello fleet")
    assert msg["id"] == 9
    assert msg["sender"] == "hanuman"
    sql, params = pg.calls[0]
    assert "INSERT INTO grove.messages" in sql
    assert params == (1, "hanuman", "hello fleet", "text", None)


def test_create_channel_normalizes_name_and_inserts():
    cols = ["id", "name", "channel_type", "description", "created_at", "updated_at", "is_archived"]
    row = (2, "fleet", "group", None, _now(), _now(), False)
    pg = _FakePg([(cols, [row], 0)])
    ch = grove.create_channel(pg, name="  #fleet ", channel_type="group")
    assert ch["name"] == "fleet"
    sql, params = pg.calls[0]
    assert "INSERT INTO grove.channels" in sql
    assert params[0] == "fleet"


def test_set_flag_rejects_unknown_flag():
    pg = _FakePg([])
    with pytest.raises(ValueError):
        grove.set_flag(pg, message_id=1, sender="hanuman", flag="not-a-real-flag")


def test_bus_send_rejects_unknown_bus_type():
    pg = _FakePg([])
    with pytest.raises(ValueError):
        grove.bus_send(pg, channel_id=1, sender="hanuman", content="x", bus_type="NOT_A_TYPE")


# ── the DB-name trap ─────────────────────────────────────────────────────────

class _MissingTableCursor(_FakeCursor):
    def execute(self, sql, params=None):
        raise psycopg2.errors.UndefinedTable('relation "grove.channels" does not exist')


class _MissingTablePg(_FakePg):
    def cursor(self):
        return _MissingTableCursor(self)


def test_list_channels_raises_grove_unavailable_naming_the_fix_on_missing_table():
    pg = _MissingTablePg([])
    with pytest.raises(grove.GroveUnavailable) as exc_info:
        grove.list_channels(pg)
    assert "WILLOW_PG_DB=willow_20" in exc_info.value.detail


def test_human_required_queue_also_translates_undefined_table():
    pg = _MissingTablePg([])
    with pytest.raises(grove.GroveUnavailable) as exc_info:
        grove.human_required_queue(pg)
    assert "willow_20" in exc_info.value.detail


# ── merge / inbox helpers (pure Python) ─────────────────────────────────────

def test_merge_attention_messages_dedupes_and_sorts_descending():
    group_a = [{"id": 1}, {"id": 3}]
    group_b = [{"id": 3}, {"id": 2}]
    merged = grove.merge_attention_messages(group_a, group_b, limit=10)
    assert [m["id"] for m in merged] == [3, 2, 1]


def test_merge_attention_messages_respects_limit():
    group = [{"id": i} for i in range(5)]
    merged = grove.merge_attention_messages(group, limit=2)
    assert len(merged) == 2
    assert [m["id"] for m in merged] == [4, 3]
