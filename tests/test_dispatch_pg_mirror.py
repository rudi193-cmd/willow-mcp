"""Best-effort Postgres mirror for dispatch packets.

Dispatch is filesystem-canonical. When an operator opts in
(`WILLOW_MCP_DISPATCH_MIRROR`) and a host DB is reachable, packet routing/status
is mirrored into `dispatch_tasks` for fleet visibility — but the mirror must
never be load-bearing: off by default, silent when no DB is present, and a DB
fault must not affect a packet that already wrote to disk.
"""
from __future__ import annotations

from willow_mcp import db, dispatch


class _FakeCursor:
    def __init__(self, conn):
        self._conn = conn

    def execute(self, sql, params=None):
        if self._conn.raise_on_execute:
            raise RuntimeError("simulated DB fault")
        self._conn.executed.append((sql, params))

    def close(self):
        pass


class _FakePg:
    def __init__(self, raise_on_execute=False):
        self.executed = []
        self.raise_on_execute = raise_on_execute

    def cursor(self):
        return _FakeCursor(self)


def _sql(fake):
    return " ".join(sql for sql, _ in fake.executed)


def test_mirror_off_by_default_never_touches_db(home, monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_DISPATCH_MIRROR", raising=False)

    def _boom():
        raise AssertionError("get_pg must not be called when the mirror is off")

    monkeypatch.setattr(db, "get_pg", _boom)
    out = dispatch.dispatch_send("willow", "hanuman", "# Task\n\ndo it")
    assert out["status"] == "pending"  # filesystem write succeeded, DB untouched


def test_mirror_upserts_on_send_and_updates_on_status(home, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_DISPATCH_MIRROR", "1")
    fake = _FakePg()
    monkeypatch.setattr(db, "get_pg", lambda: fake)

    dispatch.dispatch_send("willow", "hanuman", "# Task\n\ndo it",
                           dispatch_id="ABCD1234", summary="do it")
    blob = _sql(fake)
    assert "CREATE TABLE IF NOT EXISTS dispatch_tasks" in blob
    assert "INSERT INTO dispatch_tasks" in blob
    insert = next(p for sql, p in fake.executed if "INSERT INTO dispatch_tasks" in sql)
    assert "ABCD1234" in insert and "hanuman" in insert and "willow" in insert

    fake.executed.clear()
    dispatch.dispatch_set_status("ABCD1234", "working")
    assert "UPDATE dispatch_tasks SET status" in _sql(fake)
    upd = next(p for sql, p in fake.executed if "UPDATE dispatch_tasks" in sql)
    assert upd == ("working", "ABCD1234")


def test_mirror_on_but_no_db_is_a_silent_noop(home, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_DISPATCH_MIRROR", "1")
    monkeypatch.setattr(db, "get_pg", lambda: None)
    out = dispatch.dispatch_send("willow", "hanuman", "# Task\n\ndo it")
    assert out["status"] == "pending"  # no DB, no crash — filesystem canonical


def test_mirror_db_fault_is_swallowed_and_packet_survives(home, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_DISPATCH_MIRROR", "1")
    monkeypatch.setattr(db, "get_pg", lambda: _FakePg(raise_on_execute=True))
    out = dispatch.dispatch_send("willow", "hanuman", "# Task\n\ndo it",
                                 dispatch_id="EFGH5678")
    assert out["status"] == "pending"  # packet written despite the DB fault
    # and it is readable from the filesystem, the source of truth
    assert dispatch.dispatch_read("EFGH5678")["meta"]["to_app"] == "hanuman"
