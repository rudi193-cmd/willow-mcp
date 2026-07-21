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


def _manifest_no_app_id():
    return {"status": "warn", "reason": "no_app_id", "app_id": "", "apps_root": "/x",
            "detail": "no app_id supplied — pass the app_id you call willow-mcp with"}


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


# ── B-18: missing app_id is a caller-input warn, not a degraded verdict ───────

def test_diag_manifest_no_app_id_is_caller_input_warn(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path))
    check = server._diag_manifest("")
    assert check["status"] == "warn"
    assert check["reason"] == "no_app_id"


def test_verdict_ok_when_only_caller_input_warn():
    assert server._derive_verdict([{"severity": "warn", "caller_input": True}]) == "ok"


def test_verdict_degraded_when_caller_input_plus_real_warn():
    problems = [{"severity": "warn", "caller_input": True}, {"severity": "warn"}]
    assert server._derive_verdict(problems) == "degraded"


def test_missing_app_id_warns_but_verdict_stays_ok():
    # all subsystems healthy, caller just passed no app_id -> manifest surfaces
    # a caller_input warn, but the overall verdict is still ok.
    problems = server._derive_problems(_store_ok(), _pg_ok(), _manifest_no_app_id(), "stdio")
    mp = [p for p in problems if p["check"] == "manifest"]
    assert len(mp) == 1
    assert mp[0]["severity"] == "warn"
    assert mp[0]["caller_input"] is True
    assert server._derive_verdict(problems) == "ok"


def test_missing_egress_keys_is_warn_problem(monkeypatch):
    monkeypatch.setattr("willow_mcp.egress_setup.resolve_public_key_path", lambda: None)
    problems = server._derive_problems(_store_ok(), _pg_ok(), _manifest_ok(), "stdio")
    egress = [p for p in problems if p["check"] == "egress_keys"]
    assert len(egress) == 1
    assert egress[0]["severity"] == "warn"
    assert "setup-egress" in egress[0]["fix"]
    assert server._derive_verdict(problems) == "degraded"


def test_empty_permissions_warn_still_degrades():
    # a real manifest warn (empty permissions -> every call denied) is NOT
    # caller_input and must still degrade the verdict.
    manifest = {"status": "warn", "app_id": "demo", "apps_root": "/x",
                "detail": "manifest present but permissions empty — every call is denied"}
    problems = server._derive_problems(_store_ok(), _pg_ok(), manifest, "stdio")
    mp = [p for p in problems if p["check"] == "manifest"][0]
    assert mp["severity"] == "warn"
    assert "caller_input" not in mp
    assert server._derive_verdict(problems) == "degraded"


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


# ── learned-mapping tree (schema_rings) health ───────────────────────────────

def test_diag_rings_reports_sapling_when_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_SCHEMA_RINGS", str(tmp_path / "rings.json"))
    r = server._diag_rings()
    assert r["status"] == "ok"
    assert r["pairs"] == 0 and r["columns"] == 0
    assert r["saturation_pct"] == 0.0
    assert set(r) >= {"pairs", "cap", "columns", "confirmations", "saturation_pct"}


def test_diag_rings_counts_grown_rings_and_saturation(tmp_path, monkeypatch):
    rings = tmp_path / "rings.json"
    monkeypatch.setenv("WILLOW_MCP_SCHEMA_RINGS", str(rings))
    monkeypatch.setenv("WILLOW_MCP_SCHEMA_RINGS_MAX", "100")
    # one confirm grows two non-trivial rings (submitter->submitted_by, stat->status)
    server.sp.grow_ring({"submitted_by": {"column": "submitter"},
                         "status": {"column": "stat"}})
    r = server._diag_rings()
    assert r["pairs"] == 2 and r["cap"] == 100
    assert r["confirmations"] == 1
    assert r["saturation_pct"] == 2.0


def test_diagnostic_summary_includes_rings_check(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_SCHEMA_RINGS", str(tmp_path / "rings.json"))
    report = server.diagnostic_summary(app_id="willow")
    assert "rings" in report["checks"]
    assert report["checks"]["rings"]["backend"] == "schema-rings"
