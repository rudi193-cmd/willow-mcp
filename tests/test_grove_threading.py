"""Tests for Grove threading — recursive CTE thread walking, upward navigation,
and reply validation."""
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


def _msg_row(id, channel_id=1, sender="hanuman", content="msg", reply_to_id=None):
    """A 14-tuple matching grove._MSG_COLUMNS' order exactly."""
    return (id, channel_id, sender, content, "text", reply_to_id,
            "__all__", "EVENT", 3, None, None, None, _now(), 0)


_MSG_COLS = grove._MSG_COLUMNS.split(", ")


# ── replies create messages with reply_to_id ────────────────────────────────

def test_reply_creates_message_with_reply_to_id():
    # 1st execute(): the reply_to_id validation SELECT — target exists, same channel.
    validation = (["id", "channel_id"], [(5, 1)], 0)
    # 2nd execute(): the INSERT ... RETURNING.
    insert_row = _msg_row(9, channel_id=1, content="reply text", reply_to_id=5)
    insert = (_MSG_COLS, [insert_row], 0)
    pg = _FakePg([validation, insert])

    msg = grove.send_message(pg, channel_id=1, sender="hanuman", content="reply text", reply_to_id=5)

    assert msg["reply_to_id"] == 5
    sql, params = pg.calls[-1]
    assert "INSERT INTO grove.messages" in sql
    assert params == (1, "hanuman", "reply text", "text", 5)


# ── get_thread: recursive CTE walk downward ─────────────────────────────────

def test_get_thread_returns_direct_replies():
    cols = _MSG_COLS + ["depth"]
    rows = [
        _msg_row(2, reply_to_id=1) + (1,),
        _msg_row(3, reply_to_id=1) + (1,),
    ]
    pg = _FakePg([(cols, rows, 0)])

    result = grove.get_thread(pg, parent_id=1)

    assert len(result) == 2
    assert all(r["depth"] == 1 for r in result)
    sql, params = pg.calls[0]
    assert "WITH RECURSIVE" in sql


def test_get_thread_returns_nested_replies():
    cols = _MSG_COLS + ["depth"]
    rows = [
        _msg_row(2, reply_to_id=1) + (1,),
        _msg_row(3, reply_to_id=1) + (1,),
        _msg_row(4, reply_to_id=2) + (2,),
    ]
    pg = _FakePg([(cols, rows, 0)])

    result = grove.get_thread(pg, parent_id=1)

    assert len(result) == 3
    depths = {r["id"]: r["depth"] for r in result}
    assert depths == {2: 1, 3: 1, 4: 2}


def test_get_thread_empty():
    cols = _MSG_COLS + ["depth"]
    pg = _FakePg([(cols, [], 0)])

    result = grove.get_thread(pg, parent_id=999)

    assert result == []


def test_get_thread_respects_max_depth():
    cols = _MSG_COLS + ["depth"]
    pg = _FakePg([(cols, [], 0)])

    grove.get_thread(pg, parent_id=1, max_depth=3)

    sql, params = pg.calls[0]
    assert params == (1, 3)


# ── get_thread_root: recursive CTE walk upward ──────────────────────────────

def test_get_thread_root_from_deep_reply():
    cols = _MSG_COLS + ["hops"]
    root_row = _msg_row(1, reply_to_id=None) + (2,)
    pg = _FakePg([(cols, [root_row], 0)])

    result = grove.get_thread_root(pg, message_id=5)

    assert result["reply_to_id"] is None


def test_get_thread_root_from_root_returns_self():
    cols = _MSG_COLS + ["hops"]
    row = _msg_row(1, reply_to_id=None) + (0,)
    pg = _FakePg([(cols, [row], 0)])

    result = grove.get_thread_root(pg, message_id=1)

    assert result["id"] == 1


def test_get_thread_root_not_found():
    cols = _MSG_COLS + ["hops"]
    pg = _FakePg([(cols, [], 0)])

    result = grove.get_thread_root(pg, message_id=999)

    assert result is None


# ── reply validation ─────────────────────────────────────────────────────────

def test_reply_to_nonexistent_message_errors():
    pg = _FakePg([(None, [], 0)])

    result = grove.send_message(pg, channel_id=1, sender="hanuman", content="reply", reply_to_id=999)

    assert result["error"] == "reply_target_not_found"
    assert result["reply_to_id"] == 999


def test_cross_channel_reply_errors():
    validation = (["id", "channel_id"], [(5, 2)], 0)
    pg = _FakePg([validation])

    result = grove.send_message(pg, channel_id=1, sender="hanuman", content="reply", reply_to_id=5)

    assert result["error"] == "cross_channel_reply"


# ── the DB-name trap ─────────────────────────────────────────────────────────

class _MissingTableCursor(_FakeCursor):
    def execute(self, sql, params=None):
        raise psycopg2.errors.UndefinedTable('relation "grove.messages" does not exist')


class _MissingTablePg(_FakePg):
    def cursor(self):
        return _MissingTableCursor(self)


def test_get_thread_raises_grove_unavailable_on_missing_table():
    pg = _MissingTablePg([])
    with pytest.raises(grove.GroveUnavailable) as exc_info:
        grove.get_thread(pg, parent_id=1)
    assert "willow_20" in exc_info.value.detail
