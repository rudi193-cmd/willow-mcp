"""Tests for the severance assertion (wo-membrane-checkable, Part B).

Severance is the property that a willow-mcp install cannot see the fleet it
claims to be cut off from. Three surfaces, two kinds:

  store, postgres   DATA       — corruptible. Violation degrades.
  trust_root        AUTHORITY  — a gate this process holds the pen for.
                                 Violation breaks.

The work order's original assertion — "no resolved path in this process lies
under WILLOW_HOME" — cannot pass for any configuration: `paths.py` derives every
runtime path from `willow_home()`, so a correctly severed install has all of its
paths under WILLOW_HOME. What is checkable is that none lies under the *fleet's*
home. See `test_severed_install_reports_ok`, which is that end state.
"""
import os

import pytest

from willow_mcp import paths, server


# ── helpers ──────────────────────────────────────────────────────────────────

def _store(root):
    return {"status": "ok", "writable": True, "root": str(root), "collections": 0}


def _pg(dbname):
    return {"status": "ok", "reachable": True, "dbname": dbname, "missing": []}


def _lease(self_writable=()):
    return {"self_writable": [{"key": "lease_root", "path": p} for p in self_writable]}


@pytest.fixture
def fleet(tmp_path, monkeypatch):
    """A fleet home with willow-mcp's default layout inside it."""
    home = tmp_path / "fleet" / ".willow"
    (home / "store").mkdir(parents=True)
    (home / "mcp_apps").mkdir(parents=True)
    monkeypatch.setenv("WILLOW_MCP_FLEET_HOME", str(home))
    monkeypatch.setenv("WILLOW_MCP_FLEET_PG_DB", "willow_20")
    return home


# ── not_asserted: an install that never claimed to be severed ────────────────

def test_no_fleet_named_reports_not_asserted(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_FLEET_HOME", raising=False)
    monkeypatch.delenv("WILLOW_MCP_FLEET_PG_DB", raising=False)
    out = server._diag_severance(_store("/x/store"), _pg("willow"), _lease())
    assert out["status"] == "not_asserted"
    assert out["surfaces"] == {}


def test_not_asserted_adds_no_problems_and_keeps_verdict_ok(monkeypatch):
    """B-18's rule: a check must not make `degraded` the resting verdict for the
    many installs that legitimately share a fleet's store."""
    monkeypatch.delenv("WILLOW_MCP_FLEET_HOME", raising=False)
    monkeypatch.delenv("WILLOW_MCP_FLEET_PG_DB", raising=False)
    sev = server._diag_severance(_store("/x/store"), _pg("willow"), _lease(["/x/mcp_apps"]))
    problems = server._derive_problems(
        _store("/x/store"), _pg("willow"), {"status": "ok"}, "stdio", severance=sev)
    assert [p for p in problems if p["check"] == "severance"] == []
    assert server._derive_verdict(problems) == "ok"


# ── the end state: a correctly severed install ───────────────────────────────

def test_severed_install_reports_ok(fleet, tmp_path, monkeypatch):
    """Every path is under this install's own WILLOW_HOME — which is what
    severance looks like, and why the work order's original assertion was wrong."""
    own_home = tmp_path / "own" / ".willow-mcp"
    (own_home / "mcp_apps").mkdir(parents=True)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(own_home / "mcp_apps"))

    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), _lease())
    assert out["status"] == "ok"
    assert out["violated"] == []
    assert all(s["severed"] for s in out["surfaces"].values())


# ── data surfaces: degrade ───────────────────────────────────────────────────

def test_store_inside_fleet_home_is_violated(fleet, tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    out = server._diag_severance(_store(fleet / "store"), _pg("willow_mcp"), _lease())
    assert out["status"] == "violated"
    assert "store" in out["violated"]
    assert out["surfaces"]["store"]["severed"] is False


def test_fleet_database_is_violated(fleet, tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    out = server._diag_severance(_store(tmp_path / "own" / "store"), _pg("willow_20"), _lease())
    assert "postgres" in out["violated"]


def test_data_violation_degrades_but_does_not_break(fleet, tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    sev = server._diag_severance(_store(fleet / "store"), _pg("willow_20"), _lease())
    problems = server._derive_problems(
        _store(fleet / "store"), _pg("willow_20"), {"status": "ok"}, "stdio", severance=sev)
    sevp = [p for p in problems if p["check"] == "severance"]
    assert sevp and all(p["severity"] == "warn" for p in sevp)
    assert server._derive_verdict(problems) == "degraded"


# ── symlinks: two names, one inode ───────────────────────────────────────────

def test_symlinked_store_root_is_not_severed(fleet, tmp_path, monkeypatch):
    """`~/.willow` is a symlink into `~/github/.willow` on a real fleet host
    (probe c0b70fa2). A string prefix test calls that severed. It is not."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    link = tmp_path / "willow-link"
    link.symlink_to(fleet, target_is_directory=True)

    out = server._diag_severance(_store(link / "store"), _pg("willow_mcp"), _lease())
    assert out["surfaces"]["store"]["severed"] is False, (
        "a symlink into the fleet store is the fleet store")


# ── trust root: AUTHORITY. breaks. ───────────────────────────────────────────

def test_self_writable_trust_root_is_violated(fleet, tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"),
        _lease(["/own/mcp_apps/_net_leases"]))
    assert "trust_root" in out["violated"]


def test_trust_root_inside_fleet_home_is_violated(fleet, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(fleet / "mcp_apps"))
    out = server._diag_severance(_store("/own/store"), _pg("willow_mcp"), _lease())
    assert out["surfaces"]["trust_root"]["inside_fleet_home"] is True
    assert "trust_root" in out["violated"]


def test_trust_root_violation_breaks(fleet, tmp_path, monkeypatch):
    """B-32 and B-33 are this property, seen from the host and from the sandbox.
    A process that can rewrite the manifest granting task_net, or the consent file
    documented as the kill switch, has not been severed from anything."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    sev = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"),
        _lease([str(tmp_path / "own" / "mcp_apps" / "_net_leases")]))
    problems = server._derive_problems(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), {"status": "ok"},
        "stdio", severance=sev)
    sevp = [p for p in problems if p["check"] == "severance"]
    assert any(p["severity"] == "error" for p in sevp)
    assert server._derive_verdict(problems) == "broken"


# ── half a claim fails closed (B-25) ─────────────────────────────────────────

def test_fleet_home_without_db_leaves_postgres_unknown(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_FLEET_HOME", str(tmp_path / "fleet"))
    monkeypatch.delenv("WILLOW_MCP_FLEET_PG_DB", raising=False)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    out = server._diag_severance(_store(tmp_path / "own" / "store"), _pg("anything"), _lease())
    assert out["surfaces"]["postgres"]["severed"] is None
    assert "postgres" in out["unknown"]


def test_unknown_surface_degrades_rather_than_passing(tmp_path, monkeypatch):
    """An unverifiable claim is not a passing one."""
    monkeypatch.setenv("WILLOW_MCP_FLEET_HOME", str(tmp_path / "fleet"))
    monkeypatch.delenv("WILLOW_MCP_FLEET_PG_DB", raising=False)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    sev = server._diag_severance(_store(tmp_path / "own" / "store"), _pg("x"), _lease())
    problems = server._derive_problems(
        _store(tmp_path / "own" / "store"), _pg("x"), {"status": "ok"}, "stdio", severance=sev)
    assert server._derive_verdict(problems) == "degraded"


# ── paths: fleet_home must not default into the fleet ────────────────────────

def test_fleet_home_has_no_default(monkeypatch):
    """Defaulting to ~/.willow would make an unconfigured install declare itself
    severed from the directory it is standing in."""
    monkeypatch.delenv("WILLOW_MCP_FLEET_HOME", raising=False)
    assert paths.fleet_home() is None


def test_severance_asserted_when_either_var_set(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_FLEET_HOME", raising=False)
    monkeypatch.setenv("WILLOW_MCP_FLEET_PG_DB", "willow_20")
    assert paths.severance_asserted() is True


# ── the check must fail against today's real fleet wiring ────────────────────

def test_check_catches_the_current_install(fleet, monkeypatch):
    """The wiring wo-membrane-checkable observed at 2026-07-09T12:25Z: store and
    trust root inside the fleet home, postgres on the fleet DB, verdict `ok`.

    A check that is born green has never been observed to fail. This is the case
    it exists for, and it must come out `broken`."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(fleet / "mcp_apps"))
    store, pg = _store(fleet / "store"), _pg("willow_20")
    sev = server._diag_severance(store, pg, _lease([str(fleet / "mcp_apps" / "_net_leases")]))

    assert sev["status"] == "violated"
    assert set(sev["violated"]) == {"store", "postgres", "trust_root"}

    problems = server._derive_problems(store, pg, {"status": "ok"}, "stdio", severance=sev)
    assert server._derive_verdict(problems) == "broken"
