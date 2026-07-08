"""Tests for the self-audit tool (receipts_tail) and ReceiptLog.tail.

The audit trail is a self-legibility feature: a caller sees only its own
receipts, never another identity's.
"""
import json

import pytest

from willow_mcp import server
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


def _fn(tool):
    return getattr(tool, "fn", tool)


def test_tail_returns_own_rows_newest_first(tmp_path):
    log = ReceiptLog(str(tmp_path / "r.db"))
    log.record("me", "store_get", "ok", None)
    log.record("me", "store_put", "ok", None)
    rows = log.tail("me")
    assert [r["tool"] for r in rows] == ["store_put", "store_get"]


def test_tail_scoped_to_app_id(tmp_path):
    log = ReceiptLog(str(tmp_path / "r.db"))
    log.record("alice", "store_get", "ok", None)
    log.record("bob", "store_get", "ok", None)
    assert len(log.tail("alice")) == 1
    assert log.tail("alice")[0]["tool"] == "store_get"
    assert log.tail("nobody") == []


def test_tail_limit_clamped(tmp_path):
    log = ReceiptLog(str(tmp_path / "r.db"))
    for _ in range(5):
        log.record("me", "store_get", "ok", None)
    assert len(log.tail("me", limit=2)) == 2
    assert len(log.tail("me", limit=9999)) == 5  # clamp doesn't error


@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})  # fresh rate-limit state per test

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


def test_receipts_tail_tool_shows_own_calls(mk_app):
    app = mk_app("t", ["audit", "context"])
    # generate a call that records a receipt
    _fn(server.context_save)(app_id=app, key="k", value={"a": 1})
    out = _fn(server.receipts_tail)(app_id=app, limit=10)
    tools = [r["tool"] for r in out["receipts"]]
    assert "context_save" in tools


def test_receipts_tail_denied_without_permission(mk_app):
    app = mk_app("t", ["context"])  # no audit perm
    out = _fn(server.receipts_tail)(app_id=app, limit=10)
    assert "error" in out and "not permitted" in out["error"]
