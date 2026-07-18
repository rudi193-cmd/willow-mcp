"""whoami / diagnostic_summary must not enumerate another identity's config.

These tools are ungated (they answer even when the manifest is missing), so in
stdio they historically reported whatever app_id was passed. Under binding
enforcement they now require the caller to prove it owns that app_id — closing a
cross-identity config-disclosure primitive — while staying unchanged for a plain
local (unenforced) box.
"""
import json
import uuid

import pytest

from willow_mcp import server, signing, agent_registry as reg, session_binder as sb
from willow_mcp.db import Store
from willow_mcp.receipts import ReceiptLog


@pytest.fixture
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(tmp_path / "apps"))
    monkeypatch.delenv("WILLOW_MCP_ENFORCE_BINDING", raising=False)
    monkeypatch.setattr(server, "_store", Store(str(tmp_path / "store")))
    monkeypatch.setattr(server, "_receipt_log", ReceiptLog(str(tmp_path / "r.db")))
    monkeypatch.setattr(server, "_binder", sb.SessionBinder())
    server._CALL_CREDENTIAL.set(None)

    def _manifest(app_id, perms=("store_read",), **extra):
        d = tmp_path / "apps" / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": list(perms), **extra}))
        return app_id

    return _manifest


def _fn(tool):
    return getattr(tool, "fn", tool)


def _register_and_bind(app_id, trust):
    secret = bytes.fromhex(reg.register_agent(app_id, trust)["secret_hex"])
    header = signing.build_checkin_header(secret, app_id, trust, tools=["read"])
    sid = server._binder.check_in(header)["session_id"]
    return secret, sid


def _enforce(monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_ENFORCE_BINDING", "1")


# ── unenforced: trusted-host behavior is unchanged ────────────────────────────

def test_whoami_unenforced_reports_the_passed_app_id(env):
    env("alice", perms=("store_read",), role="reader")
    out = _fn(server.whoami)(app_id="alice")
    assert out["app_id"] == "alice" and out["role"] == "reader"


def test_whoami_unregistered_app_still_answers_under_enforcement(env, monkeypatch):
    # An unregistered app_id has no bound identity to protect — consistent with how
    # _gate treats every other tool (unregistered ⇒ manifest-only).
    env("plain", perms=("store_read",))
    _enforce(monkeypatch)
    out = _fn(server.whoami)(app_id="plain")
    assert out["app_id"] == "plain"


# ── enforced: you may only read the identity you can prove you own ────────────

def test_whoami_denies_reading_another_agents_config(env, monkeypatch):
    env("victim", perms=("full_access",), role="privileged", store_scope=["secret_*"])
    env("attacker", perms=("store_read",))
    _register_and_bind("victim", 4)
    a_secret, a_sid = _register_and_bind("attacker", 1)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    # attacker presents ITS OWN valid credential but asks about victim
    server._CALL_CREDENTIAL.set(
        {"session_id": a_sid, "call_nonce": uuid.uuid4().hex,
         "sig": sb.call_sig(a_secret, a_sid, "attacker", "whoami", "x")})
    out = _fn(server.whoami)(app_id="victim")
    assert "error" in out and "store_scope" not in out          # no config leaked


def test_whoami_denies_when_no_credential(env, monkeypatch):
    env("victim", perms=("full_access",))
    _register_and_bind("victim", 4)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    out = _fn(server.whoami)(app_id="victim")
    assert "error" in out and "binding required" in out["error"]


def test_whoami_allows_your_own_identity_with_a_valid_credential(env, monkeypatch):
    env("me", perms=("store_read",), role="mine")
    secret, sid = _register_and_bind("me", 3)
    _enforce(monkeypatch)
    nonce = uuid.uuid4().hex
    server._CALL_CREDENTIAL.set(
        {"session_id": sid, "call_nonce": nonce,
         "sig": sb.call_sig(secret, sid, "me", "whoami", nonce)})
    out = _fn(server.whoami)(app_id="me")
    assert out["app_id"] == "me" and out["role"] == "mine"


def test_diagnostic_summary_denies_another_identity_under_enforcement(env, monkeypatch):
    env("victim", perms=("full_access",))
    env("attacker", perms=("store_read",))
    _register_and_bind("victim", 4)
    a_secret, a_sid = _register_and_bind("attacker", 1)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(
        {"session_id": a_sid, "call_nonce": uuid.uuid4().hex,
         "sig": sb.call_sig(a_secret, a_sid, "attacker", "diagnostic_summary", "x")})
    out = _fn(server.diagnostic_summary)(app_id="victim")
    assert out.get("verdict") == "unauthorized"
