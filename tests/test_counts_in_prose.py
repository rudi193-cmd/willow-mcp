"""Wires tools/counts_in_prose_lint.py into CI (item G, 2026-07-30 hooks handoff
question 8). Read-only and fast, unlike tools/hook_mutation_check.py (which
mutates source in place and stays a manual tool) — safe to run on every
commit rather than by hand.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tools.counts_in_prose_lint import check, guarded_tool_count, registered_tool_count


def test_no_live_count_in_prose_has_drifted():
    problems = check()
    assert problems == [], "\n".join(problems)


def test_registered_tools_outnumber_guarded_ones_by_the_known_exceptions():
    """whoami and diagnostic_summary are the two deliberately-ungated tools
    (see server.py's own docstrings) — pin the relationship, not just each
    number in isolation, so a real accidental-ungate shows up as a count
    that no longer fits this shape."""
    assert registered_tool_count() - guarded_tool_count() == 2


def test_the_readme_mcp_badge_matches_the_sdk_this_package_pins():
    """The README badge read `MCP-1.0` while pyproject pinned `mcp>=2.0.0,<3.0.0`
    — the first thing anyone sees, advertising the wrong major version of the
    protocol SDK.

    It drifted because nothing checked it, which is the same reason the tool
    counts above needed a lint. A badge is prose about the code like any other.
    """
    import re
    import tomllib

    repo = Path(__file__).resolve().parent.parent
    pyproject = tomllib.loads((repo / "pyproject.toml").read_text())
    pin = next(d for d in pyproject["project"]["dependencies"]
               if re.match(r"^mcp\b", d))
    floor = re.search(r">=(\d+)\.", pin)
    assert floor, f"could not read a lower bound from the mcp pin: {pin!r}"

    readme = (repo / "README.md").read_text()
    badge = re.search(r"img\.shields\.io/badge/MCP-(\d+)\.(\d+)-", readme)
    assert badge, "the MCP badge is gone from README.md"
    assert badge.group(1) == floor.group(1), (
        f"README badge says MCP {badge.group(1)}.{badge.group(2)}, but pyproject "
        f"pins {pin!r}"
    )
