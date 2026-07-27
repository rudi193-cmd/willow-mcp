"""A9 — willow-mcp's trust representations pin to the fleet canonical ladder.

The 2026-07-24 box scan (A9) flagged the trust model living in three
incompatible shapes: willow-gate's ``TrustLevel`` ladder, this repo's
``session_binder.TRUST_LEVELS`` ``(name, read_only)`` (the logging view), and
``tier_policy`` (the tool-class ceiling applied over the manifest ACL at
enforcement — ``effective = manifest ∩ tier-unlocked``). Nothing cross-checks
them, so they can silently disagree, and then an agent's authority depends on
which gate evaluates it.

They express the SAME ladder today. This pins BOTH of this repo's trust
representations to the canonical below; willow-gate pins the *identical*
canonical in its own ``tests/test_trust_ladder_canonical.py``. If either repo's
ladder drifts, its test fails — the golden-vector discipline the A6
signing-encoding guard already uses across the two repos (they can't share
code: ``session_binder`` deliberately does not import willow-gate).

``query`` is a read-synonym fleet-wide (tier_policy: no capability is "query but
not read"), so it is folded into ``read`` before comparison.
"""
from willow_mcp import tier_policy
from willow_mcp.session_binder import TRUST_LEVELS as BINDER_LEVELS

# MUST be identical to CANONICAL in
# willow-gate/tests/test_trust_ladder_canonical.py — that cross-repo agreement
# is what A9 is about. Change the ladder in BOTH repos or not at all.
CANONICAL = {
    0: ("Exiled",  True,  frozenset()),
    1: ("Rookie",  True,  frozenset({"read"})),
    2: ("Steady",  False, frozenset({"read", "write"})),
    3: ("Veteran", False, frozenset({"read", "write", "execute"})),
    4: ("Elder",   False, frozenset({"read", "write", "execute", "admin"})),
}


def _fold_query(tools) -> frozenset:
    """query ≡ read fleet-wide — normalize before comparing the two ladders."""
    return frozenset("read" if t == "query" else t for t in tools)


def test_session_binder_name_and_read_only_match_canonical():
    got = {n: (name, ro) for n, (name, ro) in BINDER_LEVELS.items()}
    expected = {n: (name, ro) for n, (name, ro, _cls) in CANONICAL.items()}
    assert got == expected, (
        "session_binder.TRUST_LEVELS (name, read_only) drifted from the fleet "
        "canonical trust ladder — update BOTH repos' pins or neither (box audit A9).")


def test_tier_policy_class_ladder_matches_canonical():
    got = {n: _fold_query(cls) for n, cls in tier_policy._TIER_CLASSES.items()}
    expected = {n: cls for n, (_name, _ro, cls) in CANONICAL.items()}
    assert got == expected, (
        "tier_policy._TIER_CLASSES drifted from the fleet canonical trust ladder "
        "(query folded into read). This is the tool-class ceiling applied over the "
        "manifest ACL — it MUST match willow-gate's allowed_tools ladder (A9).")


def test_tier_policy_read_only_levels_match_canonical():
    expected = frozenset(n for n, (_name, ro, _cls) in CANONICAL.items() if ro)
    assert tier_policy._READ_ONLY_LEVELS == expected, (
        "tier_policy._READ_ONLY_LEVELS drifted from the canonical read-only "
        "levels {0, 1} (Exiled, Rookie) — must match session_binder + willow-gate (A9).")
