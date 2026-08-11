#!/usr/bin/env python3
"""envelope_mutation_check.py — per-guard mutation testing for
EnvelopeAuthority.check() in src/willow_mcp/envelopes.py.

PR #248 (envelope registry relocation) named this gap explicitly in its "Out
of scope" note: this repo has no mutation harness proving each of the
authority-check gates can actually fail, the way `safe-app-store/apps/jarvis`
does. `check()` is the fail-closed core of the constitutional envelope
system — every guard clause in it is a distinct way an agent could act
without a valid grant, and a green `tests/test_governance_continuity.py` is a
claim about that suite, not about the gate. This is the harness that turns
"we believe each errno path is covered" into a checked fact, one guard at a
time.

Modeled on `tools/hook_mutation_check.py` (same repo convention: refuse a red
baseline, restore immediately after each mutation, an outer `finally` plus a
post-loop sanity re-run so a crash mid-mutation cannot ship a mutated file),
with one correction pulled from `terpsi-music/tests/ablate.py`'s dated
lessons (2026-07-31): a nonzero pytest exit is not by itself evidence a guard
fired. A mutation that breaks import or produces a file pytest cannot collect
also exits nonzero, with no test of this suite ever having run against the
mutated line — and would be misreported as CAUGHT. So a verdict of CAUGHT
here requires a *named* pytest failure (a `FAILED <nodeid>` line), same as
ablate.py's `verdict()`. Anything else that came back non-green is reported
separately, not folded into CAUGHT.

Usage:
  envelope_mutation_check.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
TARGET_PATH = REPO_ROOT / "src" / "willow_mcp" / "envelopes.py"
TEST_TARGETS = ["tests/test_governance_continuity.py"]


class AnchorNotFound(RuntimeError):
    """The literal text a mutation expects to find and replace is gone — the
    source has moved on since this mutation was written. Refuse to guess;
    rewrite the mutation against the current source rather than silently
    skip it (a skipped mutation would just be reported as a mysterious
    gap)."""


def _replace_once(source: str, old: str, new: str, mutation_name: str) -> str:
    count = source.count(old)
    if count != 1:
        raise AnchorNotFound(
            f"[{mutation_name}] expected exactly one occurrence of the anchor "
            f"text, found {count}."
        )
    return source.replace(old, new, 1)


# ── one mutation per guard clause in EnvelopeAuthority.check() ──────────────
# (anchor text, replacement, label)

MUTATIONS = [
    # A registry that loads but holds zero active grants must be refused loudly
    # as ENOGRANTS, before the per-envelope miss below — this is the #332
    # runtime guard: a relocated $WILLOW_HOME seeds an empty starter that
    # shadows the ratified registry, and reported as a generic ENOENT it hid
    # the outage for ~60 hours. No-op'ing it falls through to "envelope not
    # active", which the ENOGRANTS test must catch.
    ('        if not registry.get("active"):\n'
     '            return {"ok": False, "errno": "ENOGRANTS", "reason": _no_grants_reason()}',
     '        if False:\n'
     '            return {"ok": False, "errno": "ENOGRANTS", "reason": _no_grants_reason()}',
     "an empty registry is refused loudly as ENOGRANTS, not a generic per-envelope miss"),

    # A duplicate/absent envelope id must be rejected as ENOENT, not silently
    # resolved to the first match — `len(matches) != 1` is doing two jobs
    # (missing AND ambiguous), and this mutation drops the ambiguous half.
    ('        if len(matches) != 1:\n'
     '            return {"ok": False, "errno": "ENOENT", "reason": "envelope not active"}',
     '        if len(matches) < 1:\n'
     '            return {"ok": False, "errno": "ENOENT", "reason": "envelope not active"}',
     "a duplicate envelope id is not silently resolved"),

    ('        if envelope.get("issued_by") != "root":\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "issuer mismatch"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "issuer mismatch"}',
     "an envelope not issued by root is refused"),

    ('        if envelope.get("revoked") or envelope.get("status") == "revoked":\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "envelope revoked"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "envelope revoked"}',
     "a revoked envelope is refused"),

    ('        if envelope.get("status") != "active":\n'
     '            return {"ok": False, "errno": "ENOENT", "reason": "envelope inactive"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "ENOENT", "reason": "envelope inactive"}',
     "a non-active envelope is refused"),

    ('        if not _granted(envelope.get("grantee"), actor):\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "grantee mismatch"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EACCES", "reason": "grantee mismatch"}',
     "an actor outside the grantee is refused"),

    ('        if not spec or spec.get("verb") != envelope.get("verb") or verb != envelope.get("verb"):\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "verb mismatch"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "verb mismatch"}',
     "a verb not matching the envelope's own verb is refused"),

    ('        if not isinstance(bounds, dict) or not isinstance(call_args, dict):\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "malformed bounds"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "malformed bounds"}',
     "non-dict bounds/call_args are refused"),

    ('        if set(bounds) != signature:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "bounds signature mismatch"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "bounds signature mismatch"}',
     "bounds not matching the syscall table's declared signature are refused"),

    ('        if failed:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "bounds mismatch", "fields": failed}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EAMBIG", "reason": "bounds mismatch", "fields": failed}',
     "call_args outside the granted bounds are refused"),

    ('        if expiry and expiry <= (now or datetime.now(timezone.utc)):\n'
     '            return {"ok": False, "errno": "EEXPIRED", "reason": "envelope expired"}',
     '        if False:\n'
     '            return {"ok": False, "errno": "EEXPIRED", "reason": "envelope expired"}',
     "an expired envelope is refused"),

    # The boundary itself: `now == expires_at` must already be expired
    # (fail-closed at the instant, not one tick after it).
    ('        if expiry and expiry <= (now or datetime.now(timezone.utc)):',
     '        if expiry and expiry < (now or datetime.now(timezone.utc)):',
     "expiry is fail-closed AT the deadline, not just after it"),

    ('            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:\n'
     '                return {"ok": False, "errno": "EAMBIG", "reason": "invalid max_count"}',
     '            if False:\n'
     '                return {"ok": False, "errno": "EAMBIG", "reason": "invalid max_count"}',
     "a malformed max_count is refused"),

    ('            if envelope.get("use_count_source") != "frank":\n'
     '                return {"ok": False, "errno": "EAMBIG", "reason": "untrusted meter"}',
     '            if False:\n'
     '                return {"ok": False, "errno": "EAMBIG", "reason": "untrusted meter"}',
     "a metered envelope not sourced from frank is refused"),

    # The quota boundary itself: `used == maximum` must already be exhausted,
    # not one citation later.
    ('            if used >= maximum:\n'
     '                return {"ok": False, "errno": "EDQUOT", "used": used, "max_count": maximum}',
     '            if used > maximum:\n'
     '                return {"ok": False, "errno": "EDQUOT", "used": used, "max_count": maximum}',
     "quota is exhausted AT max_count, not one use past it"),

    # _bound_matches: a granted list must cover EVERY item of a list actual,
    # not just one of them.
    ('            return all(\n'
     '                any(fnmatch.fnmatch(str(item), str(pattern)) for pattern in grant)\n'
     '                for item in actual\n'
     '            )',
     '            return any(\n'
     '                any(fnmatch.fnmatch(str(item), str(pattern)) for pattern in grant)\n'
     '                for item in actual\n'
     '            )',
     "a list call_arg is granted only if every item matches, not just one"),

    # _bound_matches: the scalar-grant fallback (grant not a list at all)
    # must still require exact equality.
    ('    return actual == grant\n\n\nclass EnvelopeAuthority:',
     '    return True\n\n\nclass EnvelopeAuthority:',
     "a scalar (non-list) bound still requires exact equality"),

    # _deadline: a non-string expires_at must raise, not fall through to
    # `.replace()` on a non-str (which is an unhandled crash, not the
    # fail-closed EAMBIG this function exists to produce).
    ('    if not isinstance(value, str):\n'
     '        raise ValueError("expires_at must be a timestamp/date or null")',
     '    if False:\n'
     '        raise ValueError("expires_at must be a timestamp/date or null")',
     "a non-string expires_at is refused, not crashed on"),
]


def _run_pytest() -> tuple[bool, list[str]]:
    """Run the envelope authority test suite; return (all_passed, failed_test_ids)."""
    proc = subprocess.run(
        [sys.executable, "-B", "-m", "pytest", *TEST_TARGETS, "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True,
        env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"},
    )
    failed = re.findall(r"^FAILED (\S+)", proc.stdout, re.MULTILINE)
    return proc.returncode == 0, failed


def _purge_bytecode() -> None:
    """A same-length mutation can leave a `.pyc` keyed to the mutated source
    surviving the restore (mtime+size validation only) — terpsi-music's
    ablate.py hit this for real. Clear once up front; cheap insurance."""
    for f in TARGET_PATH.parent.rglob("__pycache__/*.pyc"):
        f.unlink(missing_ok=True)


def main(argv):
    if not TARGET_PATH.exists():
        sys.stderr.write(f"[envelope_mutation_check] not found: {TARGET_PATH}\n")
        return 2
    original = TARGET_PATH.read_text()
    _purge_bytecode()

    print(f"[envelope_mutation_check] baseline: {' '.join(TEST_TARGETS)} against "
          "unmutated source...")
    passed, _ = _run_pytest()
    if not passed:
        sys.stderr.write(
            "[envelope_mutation_check] REFUSING to run: the suite is not green "
            "on unmutated source. Fix that first — every result below would be "
            "fiction otherwise.\n"
        )
        return 2
    print("[envelope_mutation_check] baseline green. Running mutations...\n")

    results = []
    try:
        for pattern, repl, label in MUTATIONS:
            try:
                mutated = _replace_once(original, pattern, repl, label)
            except AnchorNotFound as e:
                results.append((label, "ERROR", str(e)))
                continue
            TARGET_PATH.write_text(mutated)
            try:
                passed, failed = _run_pytest()
            finally:
                # Restored immediately — before any analysis or printing — so a
                # crash between here and the next line is the only window a
                # mutation could survive in, not the whole loop.
                TARGET_PATH.write_text(original)
            if passed:
                results.append((label, "GAP",
                                 "no test failed — this guard has no gate behind it"))
            elif failed:
                # A named failure: proof a real test noticed, not just that
                # pytest exited nonzero (which a collection error also does).
                results.append((label, "CAUGHT", ", ".join(sorted(failed))))
            else:
                results.append((label, "NO NAMED FAILURE",
                                 "suite exited nonzero with no FAILED test line — "
                                 "likely a collection/import error, not a guard firing"))
    finally:
        # Belt-and-suspenders: never leave a mutation in the tree, even on
        # Ctrl-C or an exception the loop didn't anticipate.
        TARGET_PATH.write_text(original)

    print("[envelope_mutation_check] sanity check: confirming restoration left "
          "the suite green...")
    passed, _ = _run_pytest()
    if not passed:
        sys.stderr.write(
            "[envelope_mutation_check] CRITICAL: the suite is NOT green after "
            "restoring the original file. Do not trust the working tree — run "
            "`git diff src/willow_mcp/envelopes.py` immediately.\n"
        )
        return 2

    print("\n=== Mutation report ===")
    gaps = 0
    for name, verdict, detail in results:
        print(f"[{verdict:16}] {name}")
        print(f"                   {detail}")
        if verdict != "CAUGHT":
            gaps += 1
    print()
    if gaps:
        print(f"{gaps} mutation(s) need attention. See report above.")
        return 1
    print(f"All {len(MUTATIONS)} guards ablate red; the suite is not decorative.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
