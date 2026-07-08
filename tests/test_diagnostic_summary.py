"""Tests for the diagnostic_summary self-check tool.

The problem-derivation and verdict logic are pure functions, so the headline
case — Postgres reachable but pointed at a database without willow-mcp's tables
(the empty-DB / wrong-WILLOW_PG_DB footgun) — is tested without a live DB.
"""
import json

from willow_mcp import server


# ── verdict logic ────────────────────────────────────────────────────────────

def test_verdict_ok_when_no_problems():
    assert server._derive_verdict([]) == "ok"


def test_verdict_degraded_on_warn_only():
    assert server._derive_verdict([{"severity": "warn"}]) == "degraded"


def test_verdict_broken_on_any_error():
    assert server._derive_verdict([{"severity": "warn"}, {"severity": "error"}]) == "broken"


# ── the empty-DB footgun ─────────────────────────────────────────────────────

def _pg_ok():
    return {"status": "ok", "reachable": True, "dbname": "willow_20", "missing": []}


def _pg_empty():
    return {"status": "warn", "reachable": True, "dbname": "willow",
            "missing": ["knowledge", "tasks", "agents", "routing_decisions"]}


def _store_ok():
    return {"status": "ok", "writable": True, "root": "/x/store", "collections": 0}


def _manifest_ok():
    return {"status": "ok", "app_id": "willow", "apps_root": "/x", "permissions": ["fleet_read"]}


def test_empty_db_is_flagged_as_error():
    problems = server._derive_problems(_store_ok(), _pg_empty(), _manifest_ok(), "stdio")
    pg_problems = [p for p in problems if p["check"] == "postgres"]
    assert len(pg_problems) == 1
    p = pg_problems[0]
    assert p["severity"] == "error"
    assert "WILLOW_PG_DB" in p["fix"]
    assert "willow" in p["detail"]
    assert server._derive_verdict(problems) == "broken"


def test_healthy_db_produces_no_problems():
    problems = server._derive_problems(_store_ok(), _pg_ok(), _manifest_ok(), "stdio")
    assert problems == []
    assert server._derive_verdict(problems) == "ok"


def test_serve_mode_adds_systemd_env_note():
    problems = server._derive_problems(_store_ok(), _pg_empty(), _manifest_ok(), "serve")
    detail = next(p["detail"] for p in problems if p["check"] == "postgres")
    assert "systemd --user" in detail


def test_postgres_unreachable_is_warn_not_error():
    pg = {"status": "fail", "reachable": False}
    problems = server._derive_problems(_store_ok(), pg, _manifest_ok(), "stdio")
    pgp = [p for p in problems if p["check"] == "postgres"][0]
    assert pgp["severity"] == "warn"  # SOIL store still works standalone
    assert server._derive_verdict(problems) == "degraded"


def test_store_not_writable_is_error():
    store = {"status": "fail", "writable": False, "root": "/x/store", "write_error": "permission denied"}
    problems = server._derive_problems(store, _pg_ok(), _manifest_ok(), "stdio")
    assert any(p["check"] == "store" and p["severity"] == "error" for p in problems)


# ── manifest check ───────────────────────────────────────────────────────────

def test_manifest_missing_is_fail(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path))
    check = server._diag_manifest("ghost")
    assert check["status"] == "fail"
    assert "no manifest" in check["detail"]


def test_manifest_group_expands_to_tools(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path))
    app_dir = tmp_path / "demo"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["fleet_read"]}))
    check = server._diag_manifest("demo")
    assert check["status"] == "ok"
    assert "fleet_status" in check["tools_allowed"]
    assert "fleet_health" in check["tools_allowed"]


def test_manifest_empty_permissions_is_warn(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path))
    app_dir = tmp_path / "demo"
    app_dir.mkdir()
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": []}))
    check = server._diag_manifest("demo")
    assert check["status"] == "warn"


# ── serve-mode redaction ─────────────────────────────────────────────────────

def test_collapse_home_redacts_paths():
    import os
    home = os.path.expanduser("~")
    obj = {"root": f"{home}/.willow/store", "nested": [f"{home}/x"]}
    out = server._collapse_home(obj)
    assert out["root"] == "~/.willow/store"
    assert out["nested"] == ["~/x"]


# ── smoke: the tool returns a well-formed report ─────────────────────────────

def test_diagnostic_summary_smoke():
    fn = getattr(server.diagnostic_summary, "fn", server.diagnostic_summary)
    rep = fn(app_id="")
    assert rep["mode"] == "stdio"
    assert rep["verdict"] in ("ok", "degraded", "broken")
    for key in ("store", "postgres", "schema", "manifest", "identity_bindings", "env"):
        assert key in rep["checks"]
    assert isinstance(rep["problems"], list)
