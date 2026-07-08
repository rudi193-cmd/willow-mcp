"""Tests for identity_binding.py — serve-mode OAuth identity binding (L-AUTH-02).
Previously untested (L-TEST-01)."""

import pytest
from willow_mcp import identity_binding as ib


@pytest.fixture
def home(tmp_path, monkeypatch):
    # conftest.py sets WILLOW_MCP_APPS_ROOT once for the whole session, and
    # _bindings_root() prefers that env var over WILLOW_HOME — without
    # overriding it here too, every test in this module would share one
    # binding directory for the whole suite regardless of tmp_path.
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "mcp_apps"))
    return tmp_path


def test_resolve_none_before_any_sign_in(home):
    assert ib.resolve_app_id("google", "sub-unknown") is None


def test_propose_creates_unconfirmed_binding(home):
    record = ib.propose_binding("google", "sub123", "a@b.com")
    assert record["confirmed"] is False
    assert record["app_id"] is None
    assert ib.resolve_app_id("google", "sub123") is None  # not confirmed yet


def test_propose_is_idempotent_does_not_clobber(home):
    first = ib.propose_binding("google", "sub123", "a@b.com")
    # A human could have confirmed it between the first and a repeat sign-in.
    ib.confirm_binding("google", "sub123", "someapp")
    second = ib.propose_binding("google", "sub123", "a@b.com")
    assert second["confirmed"] is True
    assert second["app_id"] == "someapp"


def test_confirm_then_resolve(home):
    ib.propose_binding("google", "sub123", "a@b.com")
    ib.confirm_binding("google", "sub123", "myapp")
    assert ib.resolve_app_id("google", "sub123") == "myapp"


def test_confirm_without_prior_sign_in_raises(home):
    with pytest.raises(ValueError):
        ib.confirm_binding("google", "never-signed-in", "myapp")


def test_bindings_are_scoped_per_issuer(home):
    """Same subject string under two different issuers must not collide."""
    ib.propose_binding("google", "shared-id", "a@b.com")
    ib.confirm_binding("google", "shared-id", "google-app")
    ib.propose_binding("apple", "shared-id", "a@b.com")
    ib.confirm_binding("apple", "shared-id", "apple-app")
    assert ib.resolve_app_id("google", "shared-id") == "google-app"
    assert ib.resolve_app_id("apple", "shared-id") == "apple-app"


def test_unsafe_subject_id_rejected(home):
    with pytest.raises(ValueError):
        ib.propose_binding("google", "../../etc/passwd", "a@b.com")


def test_writes_are_atomic_no_leftover_tmp(home):
    """Regression: binding writes must go through a temp file + rename, not
    a direct write_text — a crash mid-write must never leave a corrupt or
    half-written binding file behind."""
    ib.propose_binding("google", "sub123", "a@b.com")
    ib.confirm_binding("google", "sub123", "myapp")

    bindings_dir = ib.binding_path("google", "sub123").parent
    leftover = list(bindings_dir.glob("*.tmp-*"))
    assert leftover == []
    assert ib.resolve_app_id("google", "sub123") == "myapp"


# ── email_basis (§6.2) ───────────────────────────────────────────────────────

def test_email_basis_google_asserted():
    assert ib.compute_email_basis("google", "a@b.com") == "asserted"


def test_email_basis_apple_first_auth_only():
    assert ib.compute_email_basis("apple", "a@b.com") == "first_auth_only"


def test_email_basis_apple_relay():
    assert ib.compute_email_basis("apple", "abc123@privaterelay.appleid.com") == "relay"


def test_email_basis_unavailable_when_no_email():
    assert ib.compute_email_basis("apple", None) == "unavailable"
    assert ib.compute_email_basis("google", "") == "unavailable"


def test_propose_binding_records_email_basis(home):
    record = ib.propose_binding("apple", "sub123", "abc@privaterelay.appleid.com")
    assert record["email_basis"] == "relay"
    assert "verified_at" in record


# ── email drift detection (§6.3 step 4) ──────────────────────────────────────

def test_repeat_sign_in_same_email_no_drift(home):
    ib.propose_binding("google", "sub123", "a@b.com")
    second = ib.propose_binding("google", "sub123", "a@b.com")
    assert second.get("email_drift") is not True


def test_repeat_sign_in_different_email_flags_drift(home):
    ib.propose_binding("google", "sub123", "old@b.com")
    second = ib.propose_binding("google", "sub123", "new@b.com")
    assert second["email_drift"] is True
    assert second["drift_from_email"] == "old@b.com"
    assert second["drift_to_email"] == "new@b.com"
    # the stored email itself is NOT silently overwritten by drift detection
    assert second["email"] == "old@b.com"


def test_apple_email_disappearing_is_not_drift(home):
    """§6.1: Apple only sends email on the *first* authorization — its
    absence on a later sign-in is expected, not an identity change."""
    ib.propose_binding("apple", "sub123", "a@b.com")
    second = ib.propose_binding("apple", "sub123", None)
    assert second.get("email_drift") is not True
    assert second["email"] == "a@b.com"


def test_drift_does_not_overwrite_confirmed_app_id(home):
    ib.propose_binding("google", "sub123", "old@b.com")
    ib.confirm_binding("google", "sub123", "myapp")
    drifted = ib.propose_binding("google", "sub123", "new@b.com")
    assert drifted["email_drift"] is True
    assert drifted["confirmed"] is True
    assert drifted["app_id"] == "myapp"
    assert ib.resolve_app_id("google", "sub123") == "myapp"
