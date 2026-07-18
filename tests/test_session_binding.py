"""Agent identity binding (willow-gate seam Phase 2 / H1) as tested code.

Covers the keystore (register/load/list/revoke/rotate) and the binder's check_in
(HMAC + trust-ceiling cap + replay) and per-call verify_call (the SIGNED check
that closes the 'ride app_id=operator' hole).
"""
import uuid

import pytest

from willow_mcp import agent_registry as reg
from willow_mcp import session_binder as sb


@pytest.fixture(autouse=True)
def _home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_MCP_APPS_ROOT", raising=False)


def _register(agent_id, max_trust):
    return bytes.fromhex(reg.register_agent(agent_id, max_trust)["secret_hex"])


def _header(agent_id, secret, trust, *, nonce=None, reserved=0, tools=("read",)):
    h = {"agent_id": agent_id, "agent_name": agent_id, "last_gate": "t",
         "pass_count": 100, "fail_count": 0, "drift": 0,
         "nonce": nonce or uuid.uuid4().hex, "trust_level": trust,
         "timestamp": 1000, "tools": list(tools), "state_hash": "s0",
         "reserved": reserved, "signature": "0" * 64}
    h["signature"] = sb.expected_header_sig(secret, h)
    return h


# ── keystore ──────────────────────────────────────────────────────────────────

def test_register_load_roundtrip_and_secret_perms(tmp_path):
    out = reg.register_agent("op", 4)
    secret, ceiling = reg.load("op")
    assert ceiling == 4 and secret.hex() == out["secret_hex"]
    keyfile = tmp_path / "gate" / "secrets" / "op.key"
    assert oct(keyfile.stat().st_mode & 0o777) == "0o600"
    assert reg.list_agents() == {"op": 4}          # auditable, no secret


def test_reregister_rotates_secret():
    s1 = _register("op", 4)
    s2 = _register("op", 4)
    assert s1 != s2 and reg.load("op")[0] == s2


def test_revoke_removes_secret_and_entry():
    _register("op", 4)
    assert reg.revoke("op") is True
    assert reg.load("op") is None and reg.list_agents() == {}


def test_register_rejects_bad_trust():
    with pytest.raises(ValueError):
        reg.register_agent("op", 5)


def test_load_rejects_a_short_secret(tmp_path):
    reg.register_agent("op", 4)
    (tmp_path / "gate" / "secrets" / "op.key").write_bytes(b"tooshort")   # <32 bytes
    assert reg.load("op") is None                       # rejected on read, not just register


def test_is_registered_distinguishes_missing_secret(tmp_path):
    reg.register_agent("op", 4)
    (tmp_path / "gate" / "secrets" / "op.key").unlink()  # entry stays, secret gone
    assert reg.load("op") is None                        # unusable
    assert reg.is_registered("op") is True               # but still registered → must fail closed
    assert reg.is_registered("ghost") is False


# ── check_in ────────────────────────────────────────────────────────────────

def test_check_in_valid_opens_bound_session():
    secret = _register("op", 4)
    s = sb.SessionBinder().check_in(_header("op", secret, 4))
    assert s["agent_id"] == "op" and s["trust_level"] == 4 and s["tier"] == "Elder"


def test_check_in_unregistered_refused():
    with pytest.raises(sb.BindError):
        sb.SessionBinder().check_in(_header("ghost", b"g" * 32, 1))


def test_check_in_forged_signature_refused():
    _register("op", 4)
    hdr = _header("op", b"x" * 32, 4)              # signed with the wrong secret
    with pytest.raises(sb.BindError):
        sb.SessionBinder().check_in(hdr)


def test_check_in_trust_above_ceiling_refused():
    secret = _register("rookie", 1)
    with pytest.raises(sb.BindError):
        sb.SessionBinder().check_in(_header("rookie", secret, 4))   # claims Elder


def test_check_in_reserved_trap_and_replay():
    secret = _register("op", 4)
    b = sb.SessionBinder()
    with pytest.raises(sb.BindError):
        b.check_in(_header("op", secret, 4, reserved=1))
    n = uuid.uuid4().hex
    b.check_in(_header("op", secret, 4, nonce=n))
    with pytest.raises(sb.BindError):
        b.check_in(_header("op", secret, 4, nonce=n))               # replay


def test_check_in_exiled_trust0_entry_denied():
    secret = _register("exile", 0)
    with pytest.raises(sb.BindError, match="Exiled"):
        sb.SessionBinder().check_in(_header("exile", secret, 0))


def test_check_in_fails_closed_when_nonce_store_unreadable(tmp_path):
    secret = _register("op", 4)
    b = sb.SessionBinder()
    # Make the nonce file unreadable-as-a-file (a directory → OSError that is NOT
    # FileNotFoundError). The read must fail CLOSED, not treat it as "nothing used".
    b._used_nonces_file.parent.mkdir(parents=True, exist_ok=True)
    b._used_nonces_file.mkdir()
    with pytest.raises(sb.BindError, match="unreadable"):
        b.check_in(_header("op", secret, 4))


# ── per-call verify (the H1 result) ───────────────────────────────────────────

def test_verify_call_binds_a_legit_call():
    secret = _register("op", 4)
    b = sb.SessionBinder()
    sid = b.check_in(_header("op", secret, 4))["session_id"]
    cn = "cn-1"
    sig = sb.call_sig(secret, sid, "op", "store_put", cn)
    r = b.verify_call(sid, "op", "store_put", cn, sig)
    assert r["bound"] is True and r["agent_id"] == "op" and r["trust_level"] == 4


def test_verify_call_rejects_ride_replay_and_tamper():
    secret = _register("op", 4)
    b = sb.SessionBinder()
    sid = b.check_in(_header("op", secret, 4))["session_id"]
    # ride: attacker signs with its own secret
    bad = b.verify_call(sid, "op", "store_put", "n1", sb.call_sig(b"z" * 32, sid, "op", "store_put", "n1"))
    assert bad["bound"] is False and "mismatch" in bad["reason"]
    # legit consumes the nonce...
    cn = "n2"
    sig = sb.call_sig(secret, sid, "op", "store_put", cn)
    assert b.verify_call(sid, "op", "store_put", cn, sig)["bound"] is True
    # ...replay of the same nonce is refused
    assert b.verify_call(sid, "op", "store_put", cn, sig)["bound"] is False
    # tamper: reuse a sig for a different tool (fresh nonce) fails the sig check
    assert b.verify_call(sid, "op", "store_delete", "n3", sig)["bound"] is False


def test_verify_call_no_session():
    assert sb.SessionBinder().verify_call("nope", "op", "t", "n", "s")["bound"] is False
