"""tools/counts_in_prose_lint.py — catches a stale count in live prose.

Historical narrative (CHANGELOG.md, BUGS.md, SECURITY_AUDIT.md,
docs/handoffs/*, docs/migrations/*, docs/design/*-migration.md) states a count
as of a past PR or migration, on purpose (archive, don't delete) — flagging
those once the number moves on would be noise, not a guard. This only checks
LIVE, present-tense claims about the codebase's CURRENT shape: files that
describe things as they are now, not as they were at some past moment.

Found live (2026-07-31): "`_guarded` wraps 109 tools" in three files
(request_context.py, server.py, test_request_context.py) and "103 tools" in
two spots in tools/README.md — the real numbers had drifted to 103 and 105
respectively, and nothing caught it (the seed case that closes item G from
the 2026-07-30 hooks handoff, question 8). Each CHECKS entry below is one
concrete claim, checked against one concrete computation — not a general
number-scanner (dates, ports, versions, and one-off counts in prose are not
"counts that should track reality" and would just be false-positive noise).

Add a new entry when the next live claim shows up; don't try to generalize
ahead of a second real case.
"""
import ast
import re
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
_SERVER_PY = _REPO / "src" / "willow_mcp" / "server.py"


def registered_tool_count() -> int:
    """Every @mcp.tool(...) registration in server.py — the total tool
    surface, gated or not."""
    text = _SERVER_PY.read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^@mcp\.tool\(", text))


def guarded_tool_count() -> int:
    """Every @_guarded(...) application — the subset of registered tools
    that go through the permission/rate/sanitize pipeline (whoami and
    diagnostic_summary are the deliberate exceptions)."""
    text = _SERVER_PY.read_text(encoding="utf-8")
    return len(re.findall(r"(?m)^@_guarded\(", text))


def permission_group_count() -> int:
    """Keys in `gate.py`'s PERMISSION_GROUPS — read by parsing the module,
    not importing it, so the lint stays runnable without the package's
    dependencies installed.

    Added after README.md said "(42 groups)" while the real count was 43:
    `web_read` had grown a third tool and the group table a new entry, and the
    number beside the pointer to the authoritative set was the one thing not
    derived from it.
    """
    text = (_REPO / "src" / "willow_mcp" / "gate.py").read_text(encoding="utf-8")
    tree = ast.parse(text)
    for node in ast.walk(tree):
        target = getattr(node, "target", None)
        if isinstance(node, ast.AnnAssign) and getattr(target, "id", "") == "PERMISSION_GROUPS":
            return len(node.value.keys)
    raise ValueError("PERMISSION_GROUPS not found in gate.py as an annotated dict literal")


def pre_tool_use_guard_count() -> int:
    """Top-level `- ` bullets in hooks/pre_tool_use.py's own "N guards:"
    docstring list — counted from the line after "guards:" to the first
    blank line."""
    text = (_REPO / "hooks" / "pre_tool_use.py").read_text(encoding="utf-8")
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if re.match(r"^\w+ guards:$", line))
    count = 0
    for line in lines[start + 1:]:
        if not line.strip():
            break
        if line.startswith("- "):
            count += 1
    return count


_NUMBER_WORDS = {
    "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
}


def _stated_guard_count() -> int:
    text = (_REPO / "hooks" / "pre_tool_use.py").read_text(encoding="utf-8")
    m = re.search(r"(\w+) guards:", text)
    word = m.group(1).lower()
    if word not in _NUMBER_WORDS:
        raise ValueError(f"pre_tool_use.py's guard count {word!r} isn't a spelled-out number this lint knows")
    return _NUMBER_WORDS[word]


# Each entry: (file, regex-with-one-group-capturing-the-claimed-int, description,
# function computing the real value).
_LIVE_COUNT_CLAIMS = [
    ("src/willow_mcp/request_context.py", r"_guarded` wraps (\d+) tools",
     "`_guarded` wraps N tools", guarded_tool_count),
    ("src/willow_mcp/server.py", r"decorator wrapping (\d+) tools",
     "decorator wrapping N tools", guarded_tool_count),
    ("tests/test_request_context.py", r"wraps (\d+) tools",
     "`_guarded` wraps N tools", guarded_tool_count),
    ("tools/README.md", r"exposes (\d+) tools",
     "server exposes N tools", registered_tool_count),
    ("tools/README.md", r"the (\d+) willow-mcp tools",
     "the N willow-mcp tools", registered_tool_count),
    ("README.md", r"\((\d+) groups\)",
     "(N groups)", permission_group_count),
]


def check() -> list[str]:
    """Return a list of human-readable mismatches; empty means clean."""
    problems = []
    for rel_path, pattern, description, compute in _LIVE_COUNT_CLAIMS:
        path = _REPO / rel_path
        text = path.read_text(encoding="utf-8")
        matches = re.findall(pattern, text)
        if not matches:
            problems.append(f"{rel_path}: expected to find {description!r} — pattern not found "
                             f"(the prose was reworded; update this lint's entry, don't just delete it)")
            continue
        actual = compute()
        for claimed in matches:
            if int(claimed) != actual:
                problems.append(
                    f"{rel_path}: says {description.replace('N', claimed)!r}, "
                    f"but the real count is {actual}"
                )
    stated = _stated_guard_count()
    actual_bullets = pre_tool_use_guard_count()
    if stated != actual_bullets:
        problems.append(
            f"hooks/pre_tool_use.py: docstring says {stated!r} guards, "
            f"but the bullet list has {actual_bullets}"
        )
    return problems


def main() -> int:
    problems = check()
    if not problems:
        print(f"counts-in-prose: clean ({len(_LIVE_COUNT_CLAIMS) + 1} live claims checked)")
        return 0
    print("counts-in-prose: stale count(s) found —")
    for p in problems:
        print(f"  {p}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
