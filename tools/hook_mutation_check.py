#!/usr/bin/env python3
"""hook_mutation_check.py — per-guard mutation testing for
hooks/pre_tool_use.py.

A green test suite is a claim about the harness, not about the code — the
2026-07-30 handoff (docs/handoffs/2026-07-30-hooks-next-and-a-verification-
lesson.md) found six defects in verification apparatus and zero in the code
it verified, across this repo and safe-app-store. A `PreToolUse` hook is the
sharpest version of that risk: it *is* a gate, so nothing about a passing
suite distinguishes "this guard fires correctly" from "this guard never
fires" — the wrong kind of green.

This is the mutation harness that handoff's §3/§4 asked for and that did not
exist anywhere in the repo before it. It runs the six specific per-guard
mutations named there — not "delete the hook" (too coarse to be informative,
same failure as renaming a SQL trigger instead of disabling it) — and reports
which test(s), if any, caught each one. A mutation nothing catches is a guard
with no gate behind it, and that is this script's actual finding, not a
pass/fail count.

Two rules taken directly from the handoff's own defects #4 and #5:
  - REFUSE to run unless the target suite is green on unmutated source first
    (defect #4: a killed harness that starts from red poisons every number
    after it).
  - REPORT which test caught each mutation, not just that "the suite failed"
    (defect #5: a harness that prints only a pass count scores a no-op as a
    success).

And the harness never leaves a mutation in the tree: the file is restored
immediately after each mutation's test run (not after the whole loop), plus
an outer `finally` and a post-loop sanity re-run, so a Ctrl-C or a crash
mid-mutation cannot silently ship a mutated hook (the same defect #4 shape,
applied to this harness itself).

Usage:
  hook_mutation_check.py
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
HOOK_PATH = REPO_ROOT / "hooks" / "pre_tool_use.py"
# Mutated in lockstep with HOOK_PATH. Without this, every mutation would also
# make test_bundled_hook_is_identical_to_the_repo_copy fail — a true but
# uninformative "CAUGHT" that would mask whether the guard-logic tests
# themselves ever exercise the mutated behavior.
BUNDLED_PATH = REPO_ROOT / "src" / "willow_mcp" / "bundle" / "hooks" / "pre_tool_use.py"
TEST_TARGETS = [
    "tests/test_pre_tool_use_hook.py",
    "tests/test_authority_surface.py",
]


class AnchorNotFound(RuntimeError):
    """The literal text a mutation expects to find and replace is gone — the
    source has moved on since this mutation was written. Refuse to guess;
    the mutation needs to be rewritten against the current source, not
    silently skipped (a skipped mutation would just be reported as a
    mysterious gap)."""


def _replace_once(source: str, old: str, new: str, mutation_name: str) -> str:
    count = source.count(old)
    if count != 1:
        raise AnchorNotFound(
            f"[{mutation_name}] expected exactly one occurrence of the anchor "
            f"text, found {count}."
        )
    return source.replace(old, new, 1)


# ── the six mutations named in the 2026-07-30 handoff ───────────────────────

def _mutation_neutralize_client_re(source: str) -> str:
    return _replace_once(
        source,
        r'_CLIENT_RE = re.compile(r"\b(psql|psycopg[23]?|asyncpg|pg8000|sqlite3)\b")',
        r'_CLIENT_RE = re.compile(r"\b(psql|psycopg[23]?|asyncpg|pg8000)\b")',
        "neutralize _CLIENT_RE (drop sqlite3)",
    )


def _mutation_owned_marker_misses_store_root(source: str) -> str:
    return _replace_once(
        source,
        r'r"WILLOW_PG_DB|WILLOW_STORE_ROOT|\bknowledge\b|\brecords\b"',
        r'r"WILLOW_PG_DB|\bknowledge\b|\brecords\b"',
        "_OWNED_MARKER_RE misses WILLOW_STORE_ROOT",
    )


def _mutation_script_invoke_misses_cd_form(source: str) -> str:
    return _replace_once(
        source,
        r'(?:cd\s+(?P<cwd>[^\s;&|]+)\s*&&\s*)?',
        r'(?:zz_never_cd\s+(?P<cwd>[^\s;&|]+)\s*&&\s*)?',
        "_SCRIPT_INVOKE_RE misses the `cd X && python3 y.py` form",
    )


def _mutation_native_web_ignores_webfetch(source: str) -> str:
    return _replace_once(
        source,
        'if tool_name == "WebFetch":',
        'if tool_name == "WebFetchXX":',
        "check_native_web returns None for WebFetch only",
    )


def _mutation_flip_block_to_warn(source: str) -> str:
    return _replace_once(
        source,
        r'(re.compile(r"(?:^|&&|;|\|)\s*psql\b"), "block",',
        r'(re.compile(r"(?:^|&&|;|\|)\s*psql\b"), "warn",',
        "flip the psql routing entry from block to warn",
    )


def _mutation_silence_main_output(source: str) -> str:
    return _replace_once(
        source,
        "from typing import Optional",
        "from typing import Optional\n\n\n"
        "def print(*_args, **_kwargs):  # MUTATION: silence all hook output\n"
        "    return None\n",
        "main() prints nothing for any decision",
    )


MUTATIONS = [
    _mutation_neutralize_client_re,
    _mutation_owned_marker_misses_store_root,
    _mutation_script_invoke_misses_cd_form,
    _mutation_native_web_ignores_webfetch,
    _mutation_flip_block_to_warn,
    _mutation_silence_main_output,
]


def _run_pytest() -> tuple[bool, list[str]]:
    """Run the hook test suite; return (all_passed, failed_test_ids)."""
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", *TEST_TARGETS, "-q"],
        cwd=REPO_ROOT, capture_output=True, text=True,
    )
    failed = re.findall(r"^FAILED (\S+)", proc.stdout, re.MULTILINE)
    return proc.returncode == 0, failed


def _write_both(text: str) -> None:
    HOOK_PATH.write_text(text)
    BUNDLED_PATH.write_text(text)


def main(argv):
    if not HOOK_PATH.exists() or not BUNDLED_PATH.exists():
        sys.stderr.write(
            f"[hook_mutation_check] not found: {HOOK_PATH} / {BUNDLED_PATH}\n")
        return 2
    original = HOOK_PATH.read_text()
    if BUNDLED_PATH.read_text() != original:
        sys.stderr.write(
            "[hook_mutation_check] REFUSING to run: the repo and bundled "
            "copies already differ before any mutation. Fix that first — "
            "test_bundled_hook_is_identical_to_the_repo_copy should already "
            "be red.\n"
        )
        return 2

    print(f"[hook_mutation_check] baseline: {' '.join(TEST_TARGETS)} against "
          "unmutated source...")
    passed, _ = _run_pytest()
    if not passed:
        sys.stderr.write(
            "[hook_mutation_check] REFUSING to run: the suite is not green on "
            "unmutated source. Fix that first — every result below would be "
            "fiction otherwise (2026-07-30 handoff, defect #4).\n"
        )
        return 2
    print("[hook_mutation_check] baseline green. Running mutations...\n")

    results = []
    try:
        for mutate in MUTATIONS:
            try:
                mutated = mutate(original)
            except AnchorNotFound as e:
                results.append((str(e).split("]")[0][1:], "ERROR", str(e)))
                continue
            _write_both(mutated)
            try:
                passed, failed = _run_pytest()
            finally:
                # Restored immediately — before any analysis or printing —
                # so a crash between here and the next line is the only
                # window a mutation could survive in, not the whole loop.
                _write_both(original)
            label = str(mutate.__name__).lstrip("_")
            if passed:
                results.append((label, "GAP",
                                 "no test failed — this guard has no gate behind it"))
            else:
                detail = ", ".join(sorted(failed)) or "(suite failed; no FAILED lines parsed)"
                results.append((label, "CAUGHT", detail))
    finally:
        # Belt-and-suspenders: never leave a mutation in the tree, even on
        # Ctrl-C or an exception the loop didn't anticipate (2026-07-30
        # handoff, defect #4 — applied here, to this harness itself).
        _write_both(original)

    print("[hook_mutation_check] sanity check: confirming restoration left "
          "the suite green...")
    passed, _ = _run_pytest()
    if not passed:
        sys.stderr.write(
            "[hook_mutation_check] CRITICAL: the suite is NOT green after "
            "restoring the original file. Do not trust the working tree — "
            "run `git diff hooks/pre_tool_use.py src/willow_mcp/bundle/hooks/"
            "pre_tool_use.py` immediately.\n"
        )
        return 2

    print("\n=== Mutation report ===")
    gaps = 0
    for name, verdict, detail in results:
        print(f"[{verdict:6}] {name}")
        print(f"         {detail}")
        if verdict in ("GAP", "ERROR"):
            gaps += 1
    print()
    if gaps:
        print(f"{gaps} mutation(s) need attention. See report above.")
        return 1
    print(f"All {len(MUTATIONS)} mutations were caught by at least one test.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
