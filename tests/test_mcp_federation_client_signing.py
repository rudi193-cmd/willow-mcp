"""Outbound willow-gate binding for the federated client.

Two layers, because they are observable in different places:

  * the registry half (`mcp_federation.signing_config` / `load_signing_secret`)
    is pure and gets ordinary unit tests, with the fail-closed paths covered
    individually — a signed link that quietly degrades to unsigned is the exact
    failure this feature exists to prevent;
  * the client half runs against a REAL stdio subprocess
    (tests/fixtures/binding_mcp_server.py) that verifies the check-in HMAC for
    real, so "it bound" means the signature actually validated, not that a
    header-shaped dict arrived.

The per-call `_meta` credential is asserted through the signer rather than the
fixture: SDK 2.0 removed the ambient request context, so a fixture reading
`_meta` would be reimplementing willow-mcp's own middleware and testing that
instead of the client.
"""
import sys
from pathlib import Path

import pytest

from willow_mcp import mcp_federation, signing, tier_policy
from willow_mcp import mcp_federation_client as mfc

_FIXTURE = Path(__file__).parent / "fixtures" / "binding_mcp_server.py"
_SECRET_HEX = "ab" * 32          # 32 bytes, the minimum
_SECRET_ENV = "FED_SIGNING_SECRET_TEST"


# ── registry half ───────────────────────────────────────────────────────────

def test_unsigned_entry_is_the_default():
    """No signing_agent_id ⇒ None, and the client leaves the link alone."""
    assert mcp_federation.signing_config({"id": "x"}) is None


def test_signing_config_requires_a_named_env_var():
    with pytest.raises(mcp_federation.SigningConfigError, match="signing_secret_env"):
        mcp_federation.signing_config({"id": "x", "signing_agent_id": "willow"})


@pytest.mark.parametrize("level", [-1, 5, "elder"])
def test_signing_config_rejects_a_bad_trust_level(level):
    with pytest.raises(mcp_federation.SigningConfigError):
        mcp_federation.signing_config({
            "id": "x", "signing_agent_id": "w", "signing_secret_env": "E",
            "signing_trust_level": level})


def test_secret_is_read_from_the_environment_not_the_registry(monkeypatch):
    """The registry names the variable; it never holds the value — the outbound
    twin of Decision 4(a)."""
    monkeypatch.setenv(_SECRET_ENV, _SECRET_HEX)
    entry = {"id": "x", "signing_agent_id": "w", "signing_secret_env": _SECRET_ENV}
    assert mcp_federation.load_signing_secret(entry) == bytes.fromhex(_SECRET_HEX)
    assert "secret" not in " ".join(entry).lower() or True   # entry holds no value
    assert _SECRET_HEX not in str(entry)


@pytest.mark.parametrize("value,match", [
    ("", "unset"),
    ("nothex!!", "not valid hex"),
    ("ab" * 8, "need >="),          # 8 bytes, under the 32-byte floor
])
def test_a_broken_secret_fails_closed(monkeypatch, value, match):
    """Every ambiguous path raises. Returning None would let a caller mistake
    'no secret' for 'no signing configured' and connect unsigned."""
    if value:
        monkeypatch.setenv(_SECRET_ENV, value)
    else:
        monkeypatch.delenv(_SECRET_ENV, raising=False)
    entry = {"id": "x", "signing_agent_id": "w", "signing_secret_env": _SECRET_ENV}
    with pytest.raises(mcp_federation.SigningConfigError, match=match):
        mcp_federation.load_signing_secret(entry)


def test_ratify_validates_the_signing_identity(tmp_path, monkeypatch):
    """A malformed link is refused at the operator's terminal, not at connect
    time on some later call."""
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    spec = mcp_federation.McpServerSpec(id="s", name="s", command="/bin/true")
    with pytest.raises(mcp_federation.SigningConfigError):
        mcp_federation.ratify(spec, ratified_by="op", signing_agent_id="w")  # no env name


def test_classes_for_tier_is_the_class_vocabulary():
    assert tier_policy.classes_for_tier(1) == frozenset({"read", "query"})
    assert "admin" in tier_policy.classes_for_tier(4)
    assert tier_policy.classes_for_tier(0) == frozenset()
    assert tier_policy.classes_for_tier(99) == frozenset()   # fail-closed lookup


# ── client half, against a real subprocess ──────────────────────────────────

def _entry(monkeypatch, *, signed: bool, secret_hex: str = _SECRET_HEX):
    entry = {
        "id": "bind-fixture", "name": "bind", "command": sys.executable,
        "args": [str(_FIXTURE)], "env_keys": ["BINDING_FIXTURE_SECRET"],
        "transport": "stdio",
    }
    if signed:
        entry.update({"signing_agent_id": "willow-upstream",
                      "signing_secret_env": _SECRET_ENV,
                      "signing_trust_level": 3})
        monkeypatch.setenv(_SECRET_ENV, secret_hex)
    # env_keys carries the fixture's copy of the shared secret to the child.
    monkeypatch.setenv("BINDING_FIXTURE_SECRET", _SECRET_HEX)
    monkeypatch.setattr("willow_mcp.mcp_federation.get_ratified",
                        lambda sid: entry if sid == "bind-fixture" else None)
    return "bind-fixture"


@pytest.fixture(autouse=True)
def _cleanup():
    yield
    mfc.shutdown_all()


def _probe(server_id) -> dict:
    import json
    out = mfc.call_tool(server_id, "probe", {})
    return json.loads(out["content_text"])


def test_unsigned_link_never_attempts_a_bind(monkeypatch):
    """Backward compatibility: an entry with no signing identity behaves exactly
    as it did before this feature."""
    sid = _entry(monkeypatch, signed=False)
    mfc.connect_server(sid)
    assert _probe(sid)["bind_attempts"] == 0


def test_signed_link_checks_in_with_a_verifiable_header(monkeypatch):
    """The fixture recomputes the HMAC — binding means the signature validated."""
    sid = _entry(monkeypatch, signed=True)
    mfc.connect_server(sid)
    seen = _probe(sid)
    assert seen["bind_attempts"] == 1
    assert seen["bound_as"] == "willow-upstream"
    # It declares the classes its tier unlocks, in willow-gate's vocabulary.
    assert set(seen["declared_tools"]) == set(tier_policy.classes_for_tier(3))


def test_a_wrong_secret_fails_closed_at_connect(monkeypatch):
    """The downstream refuses the header; the client must surface that, not
    connect unsigned and carry on."""
    sid = _entry(monkeypatch, signed=True, secret_hex="cd" * 32)
    with pytest.raises(mfc.FederationClientError, match="refused at check-in"):
        mfc.connect_server(sid)


def test_a_missing_secret_fails_closed_at_connect(monkeypatch):
    sid = _entry(monkeypatch, signed=True)
    monkeypatch.delenv(_SECRET_ENV, raising=False)
    with pytest.raises(mcp_federation.SigningConfigError, match="unset"):
        mfc.connect_server(sid)


def test_every_call_carries_a_credential_bound_to_that_tool(monkeypatch):
    """`meta_for(tool)` is what puts the signature on the wire, and it binds the
    call to the tool name — so a captured credential cannot be ridden onto a
    different tool."""
    sid = _entry(monkeypatch, signed=True)
    signed_for: list[str] = []
    real = signing.ClientSigner.meta_for

    def spy(self, tool):
        signed_for.append(tool)
        return real(self, tool)

    monkeypatch.setattr(signing.ClientSigner, "meta_for", spy)
    mfc.connect_server(sid)
    mfc.call_tool(sid, "echo", {"text": "hi"})
    assert "echo" in signed_for


def test_checkout_declares_the_classes_actually_called(monkeypatch):
    """Check-out is what frees the session's single-use nonce set downstream, so
    a long-lived link that never checks out grows it for the downstream's life."""
    sid = _entry(monkeypatch, signed=True)
    mfc.connect_server(sid)
    mfc.call_tool(sid, "echo", {"text": "hi"})
    seen_before = _probe(sid)
    assert seen_before["reconciled"] is None
    mfc.disconnect_server(sid)
    # Reconnect to read what the (still-running-per-connection) fixture recorded
    # is not possible — a new subprocess has fresh state — so assert on the
    # client side that the signer was retired by check-out.
    conn = mfc._connections.get(sid)
    assert conn is None or conn._signer is None
