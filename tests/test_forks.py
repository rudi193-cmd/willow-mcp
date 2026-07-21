"""forks — SOIL-backed work-unit tracking through MCP."""

import json

import pytest

from willow_mcp import server
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


def _fn(tool):
    return getattr(tool, "fn", tool)


@pytest.fixture
def mk_app(tmp_path, monkeypatch):
    apps = tmp_path / "apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps))
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_buckets", {})

    def _mk(app_id, perms):
        d = apps / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": perms}))
        return app_id

    return _mk


def test_fork_create_join_log_merge(mk_app):
    app = mk_app("hanuman", ["fork_write", "fork_read"])
    created = _fn(server.fork_create)(
        app_id=app, title="feat/foo", created_by="hanuman", topic="foo")
    assert created["fork_id"].startswith("FORK-")
    fid = created["fork_id"]

    joined = _fn(server.fork_join)(app_id=app, fork_id=fid, component="kart")
    assert "kart" in joined["participants"]

    logged = _fn(server.fork_log)(
        app_id=app, fork_id=fid, component="git", type="branch",
        ref="feat/foo", description="feature branch")
    assert logged["logged"] is True

    listed = _fn(server.fork_list)(app_id=app, status="open")
    assert any(r["fork_id"] == fid for r in listed)

    st = _fn(server.fork_status)(app_id=app, fork_id=fid)
    assert st["status"] == "open"
    assert len(st["changes"]) == 1

    merged = _fn(server.fork_merge)(app_id=app, fork_id=fid, outcome_note="merged to master")
    assert merged["merged"] is True
    st2 = _fn(server.fork_status)(app_id=app, fork_id=fid)
    assert st2["status"] == "merged"


def test_fork_delete(mk_app):
    app = mk_app("hanuman", ["fork_write", "fork_read"])
    created = _fn(server.fork_create)(
        app_id=app, title="throwaway", created_by="hanuman")
    fid = created["fork_id"]
    out = _fn(server.fork_delete)(app_id=app, fork_id=fid, reason="abandon")
    assert out["deleted"] is True
    st = _fn(server.fork_status)(app_id=app, fork_id=fid)
    assert st["status"] == "deleted"


def test_env_check_clean(mk_app, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", "/tmp/willow-test")
    app = mk_app("hanuman", ["fork_write", "fork_read"])
    created = _fn(server.fork_create)(
        app_id=app, title="env", created_by="hanuman")
    fid = created["fork_id"]
    out = _fn(server.env_check)(app_id=app, fork_id=fid)
    assert out.get("clean") is True


def test_fork_denied_without_permission(mk_app):
    app = mk_app("reader", ["fork_read"])
    out = _fn(server.fork_create)(app_id=app, title="nope", created_by="reader")
    assert "error" in out
