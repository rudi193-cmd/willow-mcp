"""Tests for the willow-mcp <-> kartikeya task-queue bridge.

kartikeya is a hard dependency (B-22 close-out), so these run unconditionally.
The Postgres backend is exercised against a fake connection that records SQL —
the same style as tests/test_server.py — with the schema mapping stubbed, so no
live DB is touched.
"""
import json

import pytest

from kartikeya import QueueStats, TaskRow

from willow_mcp import task_queue as tq


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        self._conn.executed.append((sql, params))
        self._conn._last = list(self._conn.next_rows)

    def fetchall(self):
        return list(self._conn._last)

    def close(self):
        pass


class _FakePg:
    def __init__(self):
        self.executed = []
        self.next_rows = []
        self.commits = 0
        self._last = []

    def cursor(self):
        return _FakeCursor(self)

    def commit(self):
        self.commits += 1


def _mapping(result_type="jsonb", **overrides):
    fields = {f: {"column": f, "data_type": "text"} for f in tq._TASK_FIELDS}
    fields["result"]["data_type"] = result_type
    for k, v in overrides.items():
        fields[k] = v
    return {"confirmed": True, "fields": fields}


@pytest.fixture
def pg():
    return _FakePg()


@pytest.fixture
def queue(pg, monkeypatch):
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: _mapping())
    return tq.WillowMcpTaskQueue(pg, "app")


# ── construction guards ────────────────────────────────────────────────────

def test_construct_raises_on_unconfirmed_mapping(pg, monkeypatch):
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: {"confirmed": False, "fields": {}})
    with pytest.raises(RuntimeError, match="not confirmed"):
        tq.WillowMcpTaskQueue(pg, "app")


def test_construct_raises_on_resolve_error(pg, monkeypatch):
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: {"error": "table_not_found"})
    with pytest.raises(RuntimeError, match="table_not_found"):
        tq.WillowMcpTaskQueue(pg, "app")


# ── claim_pending ──────────────────────────────────────────────────────────

def test_claim_pending_atomic_sql_and_rows(queue, pg):
    pg.next_rows = [("T1", "echo hi", "kart", "willow"), ("T2", "ls", "kart", "willow")]
    rows = queue.claim_pending("kart", 5, lane="fast")
    sql, params = pg.executed[-1]
    assert "FOR UPDATE SKIP LOCKED" in sql
    assert "UPDATE tasks SET" in sql and "'running'" in sql
    assert "RETURNING" in sql
    assert params == ("kart", 5)
    assert pg.commits == 1
    assert [r.task_id for r in rows] == ["T1", "T2"]
    assert all(isinstance(r, TaskRow) for r in rows)
    assert rows[0].submitted_by == "willow"


# ── mark_done ──────────────────────────────────────────────────────────────

def test_mark_done_wraps_jsonb_result_and_stamps_completed(queue, pg):
    queue.mark_done("T1", status="completed", result=json.dumps({"stdout": "hi"}))
    sql, params = pg.executed[-1]
    assert sql.startswith("UPDATE tasks SET")
    assert "now()" in sql  # completed_at stamped
    assert params[0] == "completed"
    # jsonb column -> psycopg2 Json wrapper, not a raw string
    assert type(params[1]).__name__ == "Json"
    assert params[-1] == "T1"
    assert pg.commits == 1


def test_mark_done_plain_text_result_when_column_not_jsonb(pg, monkeypatch):
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: _mapping(result_type="text"))
    q = tq.WillowMcpTaskQueue(pg, "app")
    q.mark_done("T1", status="failed", result="boom")
    _, params = pg.executed[-1]
    assert params[1] == "boom"  # stored as-is, no Json wrapper


# ── stats ──────────────────────────────────────────────────────────────────

def test_stats_groups_by_status(queue, pg):
    pg.next_rows = [("pending", 3), ("running", 1), ("completed", 10), ("failed", 2)]
    s = queue.stats()
    assert isinstance(s, QueueStats)
    assert (s.pending, s.running, s.completed, s.failed) == (3, 1, 10, 2)
    assert s.total == 16


# ── factory: SQLite fallback when no Postgres ──────────────────────────────

def test_factory_falls_back_to_sqlite_without_postgres(tmp_path, monkeypatch):
    monkeypatch.setattr(tq, "get_pg", lambda: None)
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    q = tq.build_task_queue("app")
    from kartikeya import SqliteTaskQueue
    assert isinstance(q, SqliteTaskQueue)
    # and it actually works as a queue
    q.submit("F1", "echo hi")
    assert [r.task_id for r in q.claim_pending("kart", 5)] == ["F1"]


def test_factory_uses_postgres_when_available(monkeypatch):
    fake = _FakePg()
    monkeypatch.setattr(tq, "get_pg", lambda: fake)
    monkeypatch.setattr(tq.sp, "resolve", lambda *a, **k: _mapping())
    q = tq.build_task_queue("app")
    assert isinstance(q, tq.WillowMcpTaskQueue)
