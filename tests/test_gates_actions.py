"""Tests for gates_actions.py — the shared "press this row" logic behind
both the interactive TUI and the live local HTML dashboard.

describe() is pure and covered directly; apply() is covered against the
same local SQLite/filesystem state gates_panel.py itself reads, so a
passing test here is evidence the TUI/HTML buttons do what they claim.
"""
import pytest

from willow_mcp import gates_actions, gates_panel, identity_binding, lease, manifest_admin


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "mcp_apps"))
    monkeypatch.delenv("WILLOW_MCP_STRICT_TRUST_ROOT", raising=False)
    return tmp_path


def _row(rows, row_id):
    return next(r for r in rows if r.id == row_id)


# ── describe() — pure, no side effects ──────────────────────────────────────

def test_describe_off_permission_row_wants_toggle(home):
    manifest_admin.set_permission("app", "store_read", False)
    row = _row(gates_panel.collect("app"), "perm.app.store_write")
    assert gates_actions.describe(row).kind == "toggle_permission"


def test_describe_absent_lease_wants_grant_with_ttl_and_reason(home):
    row = _row(gates_panel.collect("app"), "lease.app")
    spec = gates_actions.describe(row)
    assert spec.kind == "lease_grant"
    assert set(spec.needs) == {"ttl", "reason"}


def test_describe_active_lease_wants_revoke(home):
    lease.grant("app", 60, issuer="op")
    row = _row(gates_panel.collect("app"), "lease.app")
    assert gates_actions.describe(row).kind == "lease_revoke"


def test_describe_consent_row_is_not_actionable(home):
    row = _row(gates_panel.collect("app"), "consent.internet")
    spec = gates_actions.describe(row)
    assert spec.kind == "none"
    assert spec.reason  # carries the same explanation the row already shows


def test_describe_env_var_row_is_not_actionable(home):
    row = _row(gates_panel.collect("app"), "strict_trust_root")
    assert gates_actions.describe(row).kind == "none"


def test_describe_unconfirmed_binding_wants_app_id(home, tmp_path):
    identity_binding.propose_binding("google", "sub123", "user@example.com")
    row = _row(gates_panel.collect("app"), "binding.google__sub123")
    spec = gates_actions.describe(row)
    assert spec.kind == "confirm_binding"
    assert spec.needs == ("app_id",)


def test_describe_confirmed_binding_is_not_actionable(home):
    identity_binding.propose_binding("google", "sub123", "u@e.com")
    identity_binding.confirm_binding("google", "sub123", "boundapp")
    row = _row(gates_panel.collect("app"), "binding.google__sub123")
    assert gates_actions.describe(row).kind == "none"


# ── apply() — toggle_permission ─────────────────────────────────────────────

def test_apply_grants_permission(home):
    row = _row(gates_panel.collect("app"), "perm.app.store_read")
    result = gates_actions.apply(row)
    assert result["ok"] is True
    assert "granted" in result["message"]
    assert "store_read" in manifest_admin.read_manifest("app")["permissions"]


def test_apply_revokes_permission(home):
    manifest_admin.set_permission("app", "store_read", True)
    row = _row(gates_panel.collect("app"), "perm.app.store_read")
    assert row.state == "on"
    result = gates_actions.apply(row)
    assert result["ok"] is True
    assert "revoked" in result["message"]
    assert "store_read" not in manifest_admin.read_manifest("app")["permissions"]


def test_apply_toggle_scopes_to_the_row_not_a_fixed_app(home):
    """Regression: in the "every app" view, each row must act on ITS OWN
    app_id (row.scope), not some app_id fixed by whoever launched the UI."""
    # Materialize both apps' manifests (a bare revoke on a nonexistent
    # manifest is a deliberate no-op — see manifest_admin.set_permission —
    # so each app needs at least one real grant to show up in list_app_ids()).
    manifest_admin.set_permission("app_a", "audit", True)
    manifest_admin.set_permission("app_b", "audit", True)
    rows = gates_panel.collect()  # no app_id -> every app
    row_b = _row(rows, "perm.app_b.store_read")
    gates_actions.apply(row_b)
    assert "store_read" in manifest_admin.read_manifest("app_b")["permissions"]
    assert "store_read" not in manifest_admin.read_manifest("app_a")["permissions"]


# ── apply() — lease grant/revoke ────────────────────────────────────────────

def test_apply_grants_lease_with_inputs(home):
    row = _row(gates_panel.collect("app"), "lease.app")
    result = gates_actions.apply(row, {"ttl": "10m", "reason": "testing", "issuer": "me"})
    assert result["ok"] is True
    st = lease.read_lease("app")
    assert st["status"] == "active"
    assert st["issuer"] == "me"
    assert st["reason"] == "testing"


def test_apply_lease_grant_defaults_ttl_and_reason(home):
    row = _row(gates_panel.collect("app"), "lease.app")
    result = gates_actions.apply(row, {})
    assert result["ok"] is True
    assert lease.read_lease("app")["status"] == "active"


def test_apply_lease_grant_rejects_bad_ttl_without_raising(home):
    row = _row(gates_panel.collect("app"), "lease.app")
    result = gates_actions.apply(row, {"ttl": "not-a-ttl"})
    assert result["ok"] is False
    assert "ttl" in result["message"].lower()
    assert lease.read_lease("app")["status"] == "none"  # nothing was granted


def test_apply_revokes_active_lease(home):
    lease.grant("app", 300, issuer="op")
    row = _row(gates_panel.collect("app"), "lease.app")
    result = gates_actions.apply(row)
    assert result["ok"] is True
    assert lease.read_lease("app")["status"] == "none"


# ── apply() — confirm_binding ───────────────────────────────────────────────

def test_apply_confirms_binding_with_app_id_input(home):
    identity_binding.propose_binding("google", "subX", "u@e.com")
    row = _row(gates_panel.collect("app"), "binding.google__subX")
    result = gates_actions.apply(row, {"app_id": "boundapp"})
    assert result["ok"] is True
    assert identity_binding.resolve_app_id("google", "subX") == "boundapp"


def test_apply_confirm_binding_without_app_id_fails_cleanly(home):
    identity_binding.propose_binding("google", "subY", "u@e.com")
    row = _row(gates_panel.collect("app"), "binding.google__subY")
    result = gates_actions.apply(row, {})
    assert result["ok"] is False
    assert identity_binding.resolve_app_id("google", "subY") is None


# ── apply() — non-actionable rows never mutate anything ─────────────────────

def test_apply_on_consent_row_does_nothing(home):
    row = _row(gates_panel.collect("app"), "consent.internet")
    before = gates_panel.collect("app")
    result = gates_actions.apply(row)
    assert result["ok"] is False
    after = gates_panel.collect("app")
    assert [r.state for r in before] == [r.state for r in after]
