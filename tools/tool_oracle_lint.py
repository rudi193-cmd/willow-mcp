"""tool_oracle_lint.py — guard the shipped tool-oracle catalog against drift.

The oracle (docs/design/nestor-tool-route.md) ships a signed bundle of
`surface -> verb` seals. If a verb is later renamed or removed, its seals point
at a canonical that no longer exists — nestor_tool_route would "serve" a dead
verb. This lint fails when any catalog canonical is not a live @mcp.tool in
server.py, so a rename can't silently leave a dangling seal.

Deliberately stdlib-only and Nestor-free: it reads the bundle as JSON and parses
server.py for verb names, so it runs in CI without the optional `nestor` extra.
Wired into CI by tests/test_tool_oracle_lint.py (the counts_in_prose_lint
pattern).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
_SERVER_PY = _REPO / "src" / "willow_mcp" / "server.py"
_BUNDLE = _REPO / "src" / "willow_mcp" / "bundle" / "tool_oracle.bundle.json"

_DEF_RE = re.compile(r"^\s*def (\w+)\(")


def live_verbs() -> set[str]:
    """Every @mcp.tool()-registered verb name in server.py — the live catalog a
    canonical must resolve to."""
    lines = _SERVER_PY.read_text(encoding="utf-8").splitlines()
    verbs: set[str] = set()
    for i, line in enumerate(lines):
        if not line.startswith("@mcp.tool("):
            continue
        # skip any further decorators (e.g. @_guarded) to the def line
        for j in range(i + 1, min(i + 6, len(lines))):
            m = _DEF_RE.match(lines[j])
            if m:
                verbs.add(m.group(1))
                break
    return verbs


def catalog_canonicals() -> list[str]:
    """The verb each shipped seal points at (pair.target_text). Empty if no
    catalog ships."""
    if not _BUNDLE.is_file():
        return []
    bundle = json.loads(_BUNDLE.read_text(encoding="utf-8"))
    return [p["target_text"] for p in bundle.get("pairs", []) if p.get("target_text")]


def dangling(canonicals, verbs) -> list[str]:
    """Pure check: canonicals that name no live verb, sorted and deduped."""
    live = set(verbs)
    return sorted({c for c in canonicals if c not in live})


def check() -> list[str]:
    """Violations for CI: one message per catalog canonical with no live verb."""
    verbs = live_verbs()
    bad = dangling(catalog_canonicals(), verbs)
    return [f"tool-oracle catalog seals '{c}' but no @mcp.tool by that name exists "
            f"in server.py (renamed or removed?)" for c in bad]


def main() -> int:
    violations = check()
    if violations:
        print("tool_oracle_lint: FAIL")
        for v in violations:
            print(f"  - {v}")
        return 1
    print(f"tool_oracle_lint: OK — {len(catalog_canonicals())} catalog canonicals "
          f"all resolve to live verbs ({len(live_verbs())} registered).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
