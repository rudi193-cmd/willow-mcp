"""Tests for the session-context tools (context_save/get/list/expire).

Backed by the SOIL store, scoped per app_id, with optional TTL. These exercise
the tools end-to-end through the _guarded pipeline (real manifest gate), so a
missing permission or a wrong identity is part of what's under test.
"""
import json
import time

import pytest

from willow_mcp import server
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


def _fn(tool):
    return getattr(tool, "fn", tool)


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


# ── the TTL predicate (pure) ─────────────────────────────────────────────────

def test_ctx_expired_past_true():
    assert server._ctx_expired({"_ctx_expires_epoch": time.time() - 10}) is True


def test_ctx_expired_future_false():
    assert server._ctx_expired({"_ctx_expires_epoch": time.time() + 1000}) is False


def test_ctx_expired_none_false():
    assert server._ctx_expired({"_ctx_expires_epoch": None}) is False
    assert server._ctx_expired({}) is False


# ── save / get / list / expire ───────────────────────────────────────────────

def test_save_get_roundtrip(mk_app):
    app = mk_app("t", ["context"])
    out = _fn(server.context_save)(app_id=app, key="cursor", value={"line": 42})
    assert out == {"key": "cursor", "expires_at": None}
    got = _fn(server.context_get)(app_id=app, key="cursor")
    assert got["value"] == {"line": 42}
    assert got["saved_at"] is not None


def test_get_missing(mk_app):
    app = mk_app("t", ["context"])
    assert _fn(server.context_get)(app_id=app, key="nope") == {"error": "not_found"}


def test_save_returns_expiry_when_ttl_set(mk_app):
    app = mk_app("t", ["context"])
    out = _fn(server.context_save)(app_id=app, key="k", value={"a": 1}, ttl_seconds=3600)
    assert out["expires_at"] is not None


def test_expired_context_is_purged_on_get(mk_app):
    app = mk_app("t", ["context"])
    # save with a tiny already-past TTL by writing directly through the store
    coll = server._ctx_collection(app)
    server._store.put(coll, {"value": {"x": 1}, "_ctx_key": "k",
                             "_ctx_expires_epoch": time.time() - 1}, record_id="k")
    assert _fn(server.context_get)(app_id=app, key="k") == {"error": "expired"}
    # purged: a second get is not_found, not expired
    assert _fn(server.context_get)(app_id=app, key="k") == {"error": "not_found"}


def test_list_skips_expired(mk_app):
    app = mk_app("t", ["context"])
    _fn(server.context_save)(app_id=app, key="live", value={"a": 1})
    coll = server._ctx_collection(app)
    server._store.put(coll, {"value": {"x": 1}, "_ctx_key": "dead",
                             "_ctx_expires_epoch": time.time() - 1}, record_id="dead")
    keys = {c["key"] for c in _fn(server.context_list)(app_id=app)["contexts"]}
    assert keys == {"live"}


def test_expire_deletes(mk_app):
    app = mk_app("t", ["context"])
    _fn(server.context_save)(app_id=app, key="k", value={"a": 1})
    assert _fn(server.context_expire)(app_id=app, key="k") == {"expired": True}
    assert _fn(server.context_get)(app_id=app, key="k") == {"error": "not_found"}


# ── per-identity isolation ───────────────────────────────────────────────────

def test_context_is_scoped_per_app(mk_app):
    a = mk_app("alice", ["context"])
    b = mk_app("bob", ["context"])
    _fn(server.context_save)(app_id=a, key="secret", value={"v": 1})
    # bob cannot see alice's context
    assert _fn(server.context_get)(app_id=b, key="secret") == {"error": "not_found"}


# ── gate ─────────────────────────────────────────────────────────────────────

def test_context_denied_without_permission(mk_app):
    app = mk_app("t", ["fleet_read"])  # no context perm
    out = _fn(server.context_save)(app_id=app, key="k", value={"a": 1})
    assert "error" in out and "not permitted" in out["error"]
