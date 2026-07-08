"""Tests for identity_binding.py — serve-mode OAuth identity binding (L-AUTH-02).
Previously untested (L-TEST-01)."""

import pytest
from willow_mcp import identity_binding as ib


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
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
