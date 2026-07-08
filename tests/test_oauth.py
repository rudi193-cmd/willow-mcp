"""Tests for oauth.py's GroveOAuthProvider — token/code lifecycle, expiry
pruning, and atomic state writes. Previously untested (L-TEST-01 follow-up).

Exercises the base GroveOAuthProvider only — no live Google/Apple network
calls needed for any of this.
"""
import asyncio
import time

import pytest
from mcp.server.auth.provider import AuthorizationParams
from mcp.shared.auth import OAuthClientInformationFull
from willow_mcp.oauth import GroveOAuthProvider


def _client(client_id="client1"):
    return OAuthClientInformationFull(
        redirect_uris=["https://example.com/callback"],
        client_id=client_id,
        client_secret="secret1",
    )


def _params():
    return AuthorizationParams(
        state="state1",
        scopes=["willow"],
        code_challenge="challenge",
        redirect_uri="https://example.com/callback",
        redirect_uri_provided_explicitly=True,
    )


@pytest.fixture
def provider(tmp_path):
    return GroveOAuthProvider(token_path=tmp_path / "mcp_token.json", base_url="http://127.0.0.1:8765")


def test_issue_and_load_authorization_code(provider):
    client = _client()
    code_str = provider.issue_code(client, _params())
    loaded = asyncio.run(provider.load_authorization_code(client, code_str))
    assert loaded is not None
    assert loaded.code == code_str


def test_load_authorization_code_wrong_client_denied(provider):
    code_str = provider.issue_code(_client("client1"), _params())
    loaded = asyncio.run(provider.load_authorization_code(_client("client2"), code_str))
    assert loaded is None


def test_exchange_authorization_code_persists_identity(provider):
    client = _client()
    code_str = provider.issue_code(client, _params(), identity={"issuer": "google", "subject": "sub123"})
    code = asyncio.run(provider.load_authorization_code(client, code_str))
    token = asyncio.run(provider.exchange_authorization_code(client, code))
    stored = provider._state["access_tokens"][token.access_token]
    assert stored["issuer"] == "google"
    assert stored["subject"] == "sub123"


def test_expired_code_pruned_on_next_issue(provider):
    client = _client()
    old_code = provider.issue_code(client, _params())
    provider._codes[old_code].expires_at = time.time() - 1  # force-expire
    provider._code_identity[old_code] = {"issuer": "google", "subject": "x"}

    provider.issue_code(client, _params())  # _prune_expired runs at the top

    assert old_code not in provider._codes
    assert old_code not in provider._code_identity


def test_prune_expired_removes_old_tokens(provider):
    provider._state["access_tokens"]["dead_access"] = {
        "token": "dead_access", "client_id": "c1", "scopes": ["willow"],
        "expires_at": time.time() - 1,
    }
    provider._state["refresh_tokens"]["dead_refresh"] = {
        "token": "dead_refresh", "client_id": "c1", "scopes": ["willow"],
        "expires_at": time.time() - 1,
    }
    provider._state["access_tokens"]["live_access"] = {
        "token": "live_access", "client_id": "c1", "scopes": ["willow"],
        "expires_at": time.time() + 3600,
    }

    provider._prune_expired()

    assert "dead_access" not in provider._state["access_tokens"]
    assert "dead_refresh" not in provider._state["refresh_tokens"]
    assert "live_access" in provider._state["access_tokens"]


def test_save_state_writes_atomically_no_leftover_tmp(provider, tmp_path):
    provider._state["clients"]["c1"] = {"redirect_uris": ["https://example.com/cb"]}
    provider._save_state()

    assert provider._token_path.exists()
    leftover = list(tmp_path.glob("*.tmp-*"))
    assert leftover == []

    import json
    reloaded = json.loads(provider._token_path.read_text())
    assert reloaded["clients"]["c1"]["redirect_uris"] == ["https://example.com/cb"]
