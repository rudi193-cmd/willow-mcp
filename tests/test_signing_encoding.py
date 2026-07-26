"""Canonical signing-encoding golden vector (box audit A6).

session_binder._canonical is the willow-mcp copy of the fleet's canonical HMAC
signing encoding. It deliberately does NOT depend on willow-gate (that package
pulls python-gnupg), so the two copies can't share code — instead both pin the
SAME golden vector. If this vector and willow-gate's
(tests/test_signing_encoding.py, constant GOLDEN) ever disagree, the encodings
have drifted apart and a header signed by one won't verify under the other; the
naive-delimiter forgery (Nestor B4) is the failure this convergence prevents.
"""
from willow_mcp.session_binder import _canonical

SAMPLE = {
    "agent_id": "sean", "agent_name": "Sean", "last_gate": "G7",
    "pass_count": 50, "fail_count": 1, "drift": -12, "nonce": "n" * 32,
    "trust_level": 4, "timestamp": 1721880000000, "tools": ["read", "write"],
    "state_hash": "a" * 64, "reserved": 0,
}

# Byte-for-byte identical to willow-gate's GOLDEN (A6 convergence).
GOLDEN = (
    '{"agent_id":"sean","agent_name":"Sean","drift":-12,"fail_count":1,'
    '"last_gate":"G7","nonce":"nnnnnnnnnnnnnnnnnnnnnnnnnnnnnnnn","pass_count":50,'
    '"reserved":0,'
    '"state_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",'
    '"timestamp":1721880000000,"tools":["read","write"],"trust_level":4}'
)


def test_canonical_encoding_matches_the_fleet_golden():
    assert _canonical(SAMPLE).decode() == GOLDEN


def test_key_order_is_stable_regardless_of_input_order():
    shuffled = dict(reversed(list(SAMPLE.items())))
    assert _canonical(shuffled).decode() == GOLDEN
