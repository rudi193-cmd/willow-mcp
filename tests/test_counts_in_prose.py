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
