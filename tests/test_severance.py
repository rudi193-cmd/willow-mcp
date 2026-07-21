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

from willow_mcp import egress_authorization, lease, paths, server


# ── helpers ──────────────────────────────────────────────────────────────────

def _store(root):
    return {"status": "ok", "writable": True, "root": str(root), "collections": 0}


def _pg(dbname):
    return {"status": "ok", "reachable": True, "dbname": dbname, "missing": []}


def _lease(self_writable=()):
    return {"self_writable": [{"key": "lease_root", "path": p} for p in self_writable]}


@pytest.fixture
def egress_locked(monkeypatch, tmp_path):
    """Put the egress surface (B-38) in its fully-severed state: strict mode on, a
    present + non-writable verification key, nothing self-writable. A tmp path is
    always writable by the test uid, so the OS-level checks must be pinned at the
    seam — that separation is a deploy step (chown), not a unit-testable one."""
    key = tmp_path / "egress.pub"
    key.write_text("x")
    monkeypatch.setenv("WILLOW_MCP_EGRESS_PUBLIC_KEY", str(key))
    monkeypatch.setattr(lease, "strict_trust_root", lambda: True)
    monkeypatch.setattr(lease, "path_is_self_writable_or_replaceable", lambda p: False)
    monkeypatch.setattr(lease, "path_is_directly_writable_for_trust", lambda p: False)
    return key


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

def test_severed_install_reports_ok(fleet, tmp_path, monkeypatch, egress_locked):
    """Every path is under this install's own WILLOW_HOME — which is what
    severance looks like, and why the work order's original assertion was wrong.

    Post-B-38 a fully-severed `ok` also requires the fourth surface: egress locked
    (strict mode on, verification key protected), supplied by `egress_locked`."""
    own_home = tmp_path / "own" / ".willow-mcp"
    (own_home / "mcp_apps").mkdir(parents=True)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(own_home / "mcp_apps"))

    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), _lease())
    assert out["status"] == "ok"
    assert out["violated"] == []
    assert all(s["severed"] for s in out["surfaces"].values())
    assert "egress" in out["surfaces"] and out["surfaces"]["egress"]["severed"] is True


def test_severed_but_strict_off_is_not_ok(fleet, tmp_path, monkeypatch):
    """B-38's thesis: an install severed on store/postgres/trust_root but with strict
    trust root OFF cannot prove network severance — it reports `partial`, not `ok`.
    This is the exact state the 2026-07-09 install was in while reporting `ok`."""
    own_home = tmp_path / "own" / ".willow-mcp"
    (own_home / "mcp_apps").mkdir(parents=True)
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(own_home / "mcp_apps"))
    monkeypatch.setattr(lease, "strict_trust_root", lambda: False)

    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), _lease())
    assert out["surfaces"]["egress"]["severed"] is None
    assert "egress" in out["unknown"]
    assert out["status"] == "partial"


# ── egress: AUTHORITY. the fourth surface (B-38). ────────────────────────────

def test_egress_forgeable_under_strict_is_violated(fleet, tmp_path, monkeypatch):
    """Strict mode ON but a key still writable → the process can forge egress →
    an authority violation that BREAKS, like trust_root."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    monkeypatch.setattr(lease, "strict_trust_root", lambda: True)
    monkeypatch.setattr(lease, "path_is_self_writable_or_replaceable", lambda p: True)
    key = tmp_path / "egress.pub"; key.write_text("x")
    monkeypatch.setenv("WILLOW_MCP_EGRESS_PUBLIC_KEY", str(key))

    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"),
        _lease([str(tmp_path / "own" / "mcp_apps" / "_net_leases")]))
    assert out["surfaces"]["egress"]["severed"] is False
    assert "egress" in out["violated"]

    problems = server._derive_problems(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), {"status": "ok"},
        "stdio", severance=out)
    egp = [p for p in problems if p["check"] == "severance" and "forge egress" in p["detail"]]
    assert egp and egp[0]["severity"] == "error"
    assert server._derive_verdict(problems) == "broken"


def test_egress_unprotected_verification_key_is_violated(fleet, tmp_path, monkeypatch, egress_locked):
    """Even with nothing else writable, an ABSENT or self-writable Ed25519 verifier
    means a forged envelope would verify — B-37's key is the reason B-38 is checkable.
    Point the verifier at a path the process can replace → violated."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    # override egress_locked's non-writable stub for the key path only
    monkeypatch.setattr(lease, "path_is_self_writable_or_replaceable", lambda p: True)

    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), _lease())
    assert out["surfaces"]["egress"]["severed"] is False
    assert "egress" in out["violated"]


def test_egress_strict_off_warns_not_breaks(fleet, tmp_path, monkeypatch):
    """Strict OFF is unknown, not violated: degrades (warn), never breaks — B-18."""
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "own" / "mcp_apps"))
    monkeypatch.setattr(lease, "strict_trust_root", lambda: False)
    out = server._diag_severance(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), _lease())
    problems = server._derive_problems(
        _store(tmp_path / "own" / "store"), _pg("willow_mcp"), {"status": "ok"},
        "stdio", severance=out)
    egp = [p for p in problems if p["check"] == "severance" and "strict trust root is off" in p["detail"]]
    assert egp and egp[0]["severity"] == "warn"
    assert server._derive_verdict(problems) in ("degraded",)


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
