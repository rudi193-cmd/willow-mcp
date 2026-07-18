"""Client-side signing shim (willow-gate H1 "practical shape").

Proves the enforcement path runs END TO END with a real signed credential riding
the MCP request's out-of-band `_meta` — the half that was previously exercised
only by tests setting the contextvar directly.
"""
import asyncio
import contextlib
import json
import types

import mcp.types as mcp_types
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

    def _manifest(app_id, perms=("full_access",)):
        d = tmp_path / "apps" / app_id
        d.mkdir(parents=True, exist_ok=True)
        (d / "manifest.json").write_text(json.dumps({"permissions": list(perms)}))
        return app_id

    return _manifest


def _register_and_bind(app_id, trust, tools=("read", "write")):
    secret = bytes.fromhex(reg.register_agent(app_id, trust)["secret_hex"])
    header = signing.build_checkin_header(secret, app_id, trust, tools=list(tools))
    session_id = server._binder.check_in(header)["session_id"]
    return secret, session_id


@contextlib.contextmanager
def _request_meta(meta_dict):
    """Simulate an incoming MCP request whose `_meta` carries `meta_dict`."""
    from mcp.server.lowlevel.server import request_ctx
    meta = mcp_types.RequestParams.Meta(**meta_dict) if meta_dict is not None else None
    token = request_ctx.set(types.SimpleNamespace(meta=meta))
    try:
        yield
    finally:
        request_ctx.reset(token)


def _enforce(monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_ENFORCE_BINDING", "1")


# ── the pure signer round-trips against the binder ────────────────────────────

def test_checkin_header_is_accepted_by_check_in(env):
    secret, sid = _register_and_bind("op", 4)
    assert sid                                    # check_in accepted the built header


def test_call_credential_verifies(env):
    secret, sid = _register_and_bind("op", 4)
    cred = signing.build_call_credential(secret, sid, "op", "store_get")
    r = server._binder.verify_call(sid, "op", "store_get", cred["call_nonce"], cred["sig"])
    assert r["bound"] is True and r["agent_id"] == "op"


def test_call_meta_wraps_under_the_shared_key():
    m = signing.call_meta(b"k" * 32, "sid", "op", "store_get")
    assert set(m) == {signing.CREDENTIAL_META_KEY}
    assert set(m[signing.CREDENTIAL_META_KEY]) == {"session_id", "call_nonce", "sig"}


def test_each_call_gets_a_fresh_nonce():
    signer = signing.ClientSigner("op", b"k" * 32, "sid")
    a = signer.meta_for("store_get")[signing.CREDENTIAL_META_KEY]["call_nonce"]
    b = signer.meta_for("store_get")[signing.CREDENTIAL_META_KEY]["call_nonce"]
    assert a != b


# ── server reads the credential from _meta ────────────────────────────────────

def test_read_call_credential_from_request_meta():
    cred = {"session_id": "s", "call_nonce": "n", "sig": "x"}
    with _request_meta({signing.CREDENTIAL_META_KEY: cred}):
        assert server._read_call_credential() == cred


def test_read_call_credential_none_without_a_request():
    assert server._read_call_credential() is None


def test_read_call_credential_none_when_malformed():
    with _request_meta({signing.CREDENTIAL_META_KEY: {"session_id": "s"}}):  # missing fields
        assert server._read_call_credential() is None


# ── end to end: a signed call rides _meta through enforcement ─────────────────

def test_signed_meta_call_passes_enforcement(env, monkeypatch):
    env("op")
    secret, sid = _register_and_bind("op", 3)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)                    # force the _meta path
    with _request_meta(signing.call_meta(secret, sid, "op", "store_get")):
        eff, err = server._gate("op", "store_get")
    assert err is None and eff == "op"


def test_unsigned_call_is_denied_under_enforcement(env, monkeypatch):
    env("op")
    _register_and_bind("op", 3)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    with _request_meta(None):                            # no _meta at all
        eff, err = server._gate("op", "store_get")
    assert eff is None and "binding required" in err["error"]


def test_meta_credential_for_wrong_tool_is_rejected(env, monkeypatch):
    env("op")
    secret, sid = _register_and_bind("op", 3)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    # signature is for store_get, but the call is store_put — sig binds the tool
    with _request_meta(signing.call_meta(secret, sid, "op", "store_get")):
        eff, err = server._gate("op", "store_put")
    assert eff is None and "binding rejected" in err["error"]


# ── the bootstrap exemption ───────────────────────────────────────────────────

def test_session_bind_is_exempt_from_the_per_call_credential(env, monkeypatch):
    env("op")
    reg.register_agent("op", 3)                          # registered, but no session yet
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    with _request_meta(None):                            # no credential possible pre-check-in
        eff, err = server._gate("op", "session_bind")
    assert err is None and eff == "op"                   # bootstrap allowed


def test_only_session_bind_is_exempt(env, monkeypatch):
    env("op")
    reg.register_agent("op", 3)
    _enforce(monkeypatch)
    server._CALL_CREDENTIAL.set(None)
    with _request_meta(None):
        eff, err = server._gate("op", "session_reconcile")   # not a bootstrap tool
    assert eff is None and "binding required" in err["error"]


# ── the client convenience helper attaches meta ───────────────────────────────

def test_signed_call_tool_attaches_meta_not_arguments():
    captured = {}

    class _FakeSession:
        async def call_tool(self, name, arguments=None, *, meta=None, **kw):
            captured.update(name=name, arguments=arguments, meta=meta)
            return "ok"

    signer = signing.ClientSigner("op", b"k" * 32, "sid")
    out = asyncio.run(signing.signed_call_tool(
        _FakeSession(), signer, "store_get", {"app_id": "op", "id": "x"}))
    assert out == "ok"
    assert captured["arguments"] == {"app_id": "op", "id": "x"}   # credential NOT here
    assert signing.CREDENTIAL_META_KEY in captured["meta"]        # it's in _meta
    assert captured["meta"][signing.CREDENTIAL_META_KEY]["session_id"] == "sid"
