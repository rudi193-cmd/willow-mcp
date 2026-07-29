"""subject_consent.core — the fail-closed, stdlib-only guardian-consent engine.

Two properties are load-bearing and each has its own section below:

  1. **Fail-closed.** Exactly like willow_mcp.consent, anything we cannot read
     as a verified GRANTED denies: an absent store, an unparseable chain, a
     tampered chain, no record, a pending grant, a revocation — all `False`.
     Consent is never inferred; absence is not consent.

  2. **Egress-free / stdlib-only.** The core runs on a child's device (UTETY)
     and under corpus-lens's stdlib-only charter, so `core` must import nothing
     but the standard library — no willow_mcp runtime, no network stack. This
     mirrors UTETY's test_boundaries.py: the boundary is a test, not a comment.

A third, cross-cutting property lives in the DRIFT-GUARD section at the bottom:
this package is a VENDORED copy of the canonical safe-app-store
``libs/subject-consent`` (box audit A1). Its code body must not diverge in
place — the pinned-hash test below fires on any local edit, and the CI job
`vendor-sync` (scripts/check_subject_consent_sync.py) catches the canonical
advancing past us. Mirrors the friction_floor drift-guard added in #185.
"""
import ast
import hashlib
import sys
from pathlib import Path

import pytest

from willow_mcp.subject_consent import core
from willow_mcp.subject_consent.core import (
    ChainTamperError,
    DeidentificationError,
    SubjectConsentError,
    deidentify,
    grant,
    permitted,
    read_disclosures,
    record_disclosure,
    revoke,
    verify_consent_chain,
)

OWNER = "operator"


# ── fail-closed: the gate denies on every path that isn't a verified GRANTED ──

def test_absent_store_denies(tmp_path):
    # nothing written yet — the file does not exist
    assert permitted(tmp_path, "subj-1", "kb_promotion") is False


def test_unknown_scope_denies(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    assert permitted(tmp_path, "subj-1", "not_a_real_scope") is False


def test_no_record_for_pair_denies(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    # same subject, different scope → no grant for THIS pair
    assert permitted(tmp_path, "subj-1", "person_inference") is False
    # same scope, different subject
    assert permitted(tmp_path, "subj-2", "kb_promotion") is False


def test_grant_permits_only_its_pair(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    assert permitted(tmp_path, "subj-1", "kb_promotion") is True


def test_revoke_denies_from_then_on(tmp_path):
    grant(tmp_path, "subj-1", "person_inference", OWNER)
    assert permitted(tmp_path, "subj-1", "person_inference") is True
    revoke(tmp_path, "subj-1", "person_inference", OWNER)
    assert permitted(tmp_path, "subj-1", "person_inference") is False


def test_regrant_after_revoke_permits_again(tmp_path):
    # latest transition wins — the chain is a history, not a one-way latch
    grant(tmp_path, "subj-1", "local_only", OWNER)
    revoke(tmp_path, "subj-1", "local_only", OWNER)
    grant(tmp_path, "subj-1", "local_only", OWNER)
    assert permitted(tmp_path, "subj-1", "local_only") is True


def test_grant_rejects_unknown_scope(tmp_path):
    with pytest.raises(SubjectConsentError):
        grant(tmp_path, "subj-1", "telepathy", OWNER)


def test_grant_rejects_empty_grantor(tmp_path):
    with pytest.raises(SubjectConsentError):
        grant(tmp_path, "subj-1", "kb_promotion", "   ")


def test_grant_rejects_empty_subject(tmp_path):
    with pytest.raises(SubjectConsentError):
        grant(tmp_path, "  ", "kb_promotion", OWNER)


def test_owner_is_not_special_cased(tmp_path):
    # the core does not know who the owner is; owner==subject still needs a grant
    assert permitted(tmp_path, OWNER, "kb_promotion") is False
    grant(tmp_path, OWNER, "kb_promotion", OWNER)
    assert permitted(tmp_path, OWNER, "kb_promotion") is True


# ── tamper-evidence: an edited or truncated chain denies AND is detectable ────

def test_tampered_chain_denies_silently_at_gate(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    path = tmp_path / "consent.jsonl"
    rows = path.read_text(encoding="utf-8").splitlines()
    # flip the status in place without recomputing the hash
    tampered = rows[0].replace('"granted"', '"revoked"') if '"granted"' in rows[0] else rows[0]
    if tampered == rows[0]:
        tampered = rows[0].replace("granted", "grantedX")
    path.write_text(tampered + "\n", encoding="utf-8")
    # the gate never raises — it just denies
    assert permitted(tmp_path, "subj-1", "kb_promotion") is False


def test_tampered_chain_raises_on_admin_verify(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    path = tmp_path / "consent.jsonl"
    row = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(row.replace("kb_promotion", "person_inference") + "\n", encoding="utf-8")
    with pytest.raises(ChainTamperError):
        verify_consent_chain(tmp_path)


def test_verify_absent_chain_is_not_tampered(tmp_path):
    # a store that was never written is clean, not broken
    verify_consent_chain(tmp_path)  # must not raise


def test_append_refuses_to_extend_broken_chain(tmp_path):
    grant(tmp_path, "subj-1", "kb_promotion", OWNER)
    path = tmp_path / "consent.jsonl"
    row = path.read_text(encoding="utf-8").splitlines()[0]
    path.write_text(row.replace("subj-1", "subj-X") + "\n", encoding="utf-8")
    with pytest.raises(ChainTamperError):
        grant(tmp_path, "subj-2", "kb_promotion", OWNER)


# ── de-identify-or-refuse: the scrub is proven or it raises, value never echoed ─

def test_deidentify_removes_identifier(tmp_path):
    out = deidentify("Alex went to the park", ["Alex"])
    assert "Alex" not in out
    assert "park" in out


def test_deidentify_is_case_insensitive(tmp_path):
    out = deidentify("ALEX and alex and Alex", ["Alex"])
    assert "alex" not in out.lower()


def test_deidentify_ignores_empty_identifiers(tmp_path):
    out = deidentify("nothing to scrub", ["", None])  # type: ignore[list-item]
    assert out == "nothing to scrub"


def test_deidentify_error_never_carries_the_value():
    # if the scrub could somehow fail, the exception must not leak the secret.
    # force failure by monkeypatching is overkill; instead assert the contract on
    # the message of a deliberately-constructed failure.
    err = DeidentificationError("de-identification failed to clean the text")
    assert "failed to clean" in str(err)
    # the class contract: no value is ever formatted into the message by core.
    src = Path(core.__file__).read_text(encoding="utf-8")
    # the raise site must not interpolate `ident` or `out`/`text` into the message
    assert "raise DeidentificationError(" in src
    for bad in ("{ident", "{out", "{text", "{needle"):
        assert bad not in src, f"de-identification error must not echo {bad!r}"


# ── disclosure chain: the guardian's readable, tamper-evident record ──────────

def test_disclosure_roundtrips(tmp_path):
    record_disclosure(tmp_path, "subj-1", "lesson", "covered fractions")
    record_disclosure(tmp_path, "subj-1", "lesson", "covered decimals")
    rows = read_disclosures(tmp_path, "subj-1")
    assert [r["detail"] for r in rows] == ["covered fractions", "covered decimals"]


def test_disclosure_is_per_subject(tmp_path):
    record_disclosure(tmp_path, "subj-1", "lesson", "A")
    record_disclosure(tmp_path, "subj-2", "lesson", "B")
    assert [r["detail"] for r in read_disclosures(tmp_path, "subj-1")] == ["A"]
    assert [r["detail"] for r in read_disclosures(tmp_path, "subj-2")] == ["B"]


def test_disclosure_absent_is_empty(tmp_path):
    assert read_disclosures(tmp_path, "nobody") == []


def test_disclosure_tamper_raises(tmp_path):
    record_disclosure(tmp_path, "subj-1", "lesson", "A")
    # corrupt the CHAIN file (there is also a sibling .anchor.json now)
    ddir = tmp_path / "disclosures"
    f = next(p for p in ddir.iterdir() if p.suffix == ".jsonl")
    row = f.read_text(encoding="utf-8").splitlines()[0]
    f.write_text(row.replace("lesson", "surveillance") + "\n", encoding="utf-8")
    with pytest.raises(ChainTamperError):
        read_disclosures(tmp_path, "subj-1")


def test_disclosure_truncation_is_detected(tmp_path):
    # the anchor guard (UTETY audit B4): a truncated chain still links cleanly
    for d in ("A", "B", "C"):
        record_disclosure(tmp_path, "subj-1", "lesson", d)
    f = next(p for p in (tmp_path / "disclosures").iterdir() if p.suffix == ".jsonl")
    lines = f.read_text(encoding="utf-8").splitlines()
    f.write_text("\n".join(lines[:-1]) + "\n", encoding="utf-8")
    with pytest.raises(ChainTamperError):
        read_disclosures(tmp_path, "subj-1")


def test_disclosure_filename_does_not_leak_subject_id(tmp_path):
    record_disclosure(tmp_path, "very-identifying-name", "lesson", "A")
    names = [p.name for p in (tmp_path / "disclosures").iterdir()]
    assert all("very-identifying-name" not in n for n in names)


# ── boundary: core imports stdlib only (mirrors UTETY test_boundaries.py) ─────

_STDLIB = set(getattr(sys, "stdlib_module_names", set())) | {"__future__"}


def test_core_imports_stdlib_only():
    """Static assertion: every top-level import in core.py resolves to the
    standard library. No willow_mcp runtime, no third-party, no network client
    may sneak into the child-device / stdlib-charter core."""
    src = Path(core.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.level and node.level > 0:
                pytest.fail("core.py must have no relative (package-local) imports")
            if node.module:
                imported.add(node.module.split(".")[0])
    offenders = sorted(m for m in imported if m not in _STDLIB)
    assert not offenders, f"core.py imports non-stdlib modules: {offenders}"


def test_core_has_no_network_or_subprocess_imports():
    """Belt-and-suspenders over the allowlist: name the egress/exec modules
    explicitly so a future edit that adds one fails loudly, even if it is
    technically stdlib (socket, urllib, http, subprocess all are)."""
    src = Path(core.__file__).read_text(encoding="utf-8")
    tree = ast.parse(src)
    banned = {"socket", "ssl", "urllib", "http", "ftplib", "smtplib",
              "subprocess", "asyncio", "requests", "httpx", "aiohttp"}
    for node in ast.walk(tree):
        mods: list[str] = []
        if isinstance(node, ast.Import):
            mods = [a.name.split(".")[0] for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.module:
            mods = [node.module.split(".")[0]]
        hit = sorted(set(mods) & banned)
        assert not hit, f"core.py must not import egress/exec modules: {hit}"


# ── drift-guard: the vendored package must not silently diverge from canonical ──
# Finding A1 of the 2026-07-24 box audit: subject_consent is vendored in three
# repos, each carrying a "canonical lives at safe-app-store, keep in sync"
# docstring — but nothing enforced it. This pins the CODE BODY of each vendored
# module (from `from __future__` onward — the docstring is deliberately excluded
# because the vendored copy adds a provenance stanza the canonical lacks) to a
# known hash, so ANY local edit fails loudly. Companion CI job `vendor-sync`
# (scripts/check_subject_consent_sync.py) catches the other direction: canonical
# advancing while this copy stays behind. Same two-sided guard as #185's
# friction_floor.
#
# The copy is not a place to edit. To adopt a canonical change: sync the code
# body from safe-app-store libs/subject-consent, keep this repo's provenance
# docstring stanza, then update the pinned hash to the value the assertion
# prints.
_PKG = Path(__file__).resolve().parents[1] / "src/willow_mcp/subject_consent"
_MARKER = "from __future__ import annotations"

#: sha256 of each module's code body (from _MARKER to EOF), pinned to the
#: canonical safe-app-store libs/subject-consent copy.
EXPECTED_BODY_SHA256 = {
    "__init__.py": "81ed754027759edd081ea431dee8d3f14ac96832ce16d7a4f1c630ca98786ed6",
    "core.py": "d08d13033140672d3b8974f64231dd352ec92ff2de2a861c196af1552ba16a7c",
}


def _body(text: str) -> str:
    return text[text.index(_MARKER):]  # code only — docstring/provenance excluded


@pytest.mark.parametrize("mod", sorted(EXPECTED_BODY_SHA256))
def test_vendored_body_matches_pinned_hash(mod):
    got = hashlib.sha256(_body((_PKG / mod).read_text(encoding="utf-8")).encode()).hexdigest()
    assert got == EXPECTED_BODY_SHA256[mod], (
        f"vendored subject_consent/{mod} code body drifted from the pinned "
        "safe-app-store canonical copy.\n"
        f"  got:      {got}\n  expected: {EXPECTED_BODY_SHA256[mod]}\n"
        "If you re-synced from safe-app-store on purpose, update "
        "EXPECTED_BODY_SHA256.\n"
        "If you edited the vendored copy directly — don't; edit the canonical "
        "libs/subject-consent and re-sync.")
