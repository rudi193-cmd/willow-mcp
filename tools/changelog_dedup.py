#!/usr/bin/env python3
"""Rebuild the newest CHANGELOG section from the commits, dropping merge commits.

WHY THIS EXISTS
---------------
This repo merges with merge commits rather than squashing. GitHub writes the PR
title into the merge commit *body*:

    subject: Merge pull request #264 from rudi193-cmd/claude/...
    body:    fix(web_search): make the trusted-domain list answerable to jeles' registry

release-please parses that body, so one change reaches it twice — once as the
real commit, once as the merge commit that carried its title. Two things follow,
and the second is the one that matters:

  * **Duplicates.** 2.1.2 listed the same fix twice, from `eddaf85` (the merge)
    and `49b95fe` (the commit).
  * **Dropped commits.** release-please collapses entries that share a scope, and
    the merge commit can win. 2.1.3 listed the merge commit's title and lost
    `0073767` entirely — a shipped fix, absent from the changelog, with a
    synthetic entry standing where it should have been. A duplicate is noise; a
    missing entry means released work is undocumented.

Both were corrected by hand for 2.1.2, 2.1.3 and jeles 0.5.0. This is that
correction made repeatable, so it happens before the release rather than after.

WHAT IT DOES
------------
Rebuilds the topmost section from `git log <previous tag>..HEAD`: every non-merge
commit whose type is not hidden in release-please-config.json, each listed once,
grouped in config order. Merge commits are excluded by construction — a commit
with two parents is never an entry, whatever its body says.

WHAT IT REFUSES TO DO
---------------------
It rewrites only what it fully understands, and bails out loudly otherwise:

  * a heading in the section that is not a configured section name (a breaking
    change produces "⚠ BREAKING CHANGES", whose formatting this does not model);
  * any commit in the range carrying `!` or a `BREAKING CHANGE:` footer;
  * a previous tag that is not in the repository.

Bailing prints the reason and exits 2. That is deliberate: silently rewriting a
release note it had misread would be a worse failure than the one it fixes.

USAGE
-----
    python tools/changelog_dedup.py            # fix in place
    python tools/changelog_dedup.py --check    # exit 1 if it would change anything
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
CHANGELOG = REPO / "CHANGELOG.md"
CONFIG = REPO / "release-please-config.json"

# "## [2.1.3](https://github.com/o/r/compare/v2.1.2...v2.1.3) (2026-08-04)"
SECTION_RE = re.compile(
    r"^## \[(?P<version>[^\]]+)\]\((?P<url>(?P<base>https://[^/]+/[^/]+/[^/]+)"
    r"/compare/(?P<prev>[^.]+(?:\.[^.]+)*?)\.\.\.(?P<new>[^)]+))\)(?P<rest>.*)$"
)
HEADING_RE = re.compile(r"^### (?P<name>.+?)\s*$")
CONVENTIONAL_RE = re.compile(
    r"^(?P<type>[a-z]+)(?:\((?P<scope>[^)]*)\))?(?P<breaking>!)?:\s*(?P<desc>.+)$"
)
# A real breaking-change footer starts a line and ends with a colon. The first
# version of this was `"BREAKING CHANGE" in body`, which flagged the commit that
# introduced this file — its message *describes* breaking-change handling. A
# substring search cannot tell a footer from prose about footers, and the same
# mistake had already been made once in this repo with `GITHUB_TOKEN`.
BREAKING_FOOTER_RE = re.compile(r"^BREAKING[ -]CHANGE:", re.MULTILINE)


class Bail(Exception):
    """Something outside what this tool models. Refuse rather than guess."""


def git(*args: str) -> str:
    out = subprocess.run(["git", "-C", str(REPO), *args],
                         capture_output=True, text=True)
    if out.returncode != 0:
        raise Bail(f"git {' '.join(args)} failed: {out.stderr.strip()}")
    return out.stdout


def sections_from_config() -> tuple[dict[str, str], list[str]]:
    """(type -> section name) for un-hidden types, plus section order."""
    entries = json.loads(CONFIG.read_text())["packages"]["."]["changelog-sections"]
    visible = {e["type"]: e["section"] for e in entries if not e.get("hidden")}
    order: list[str] = []
    for e in entries:
        if not e.get("hidden") and e["section"] not in order:
            order.append(e["section"])
    return visible, order


def commits_in_range(prev_tag: str, new_tag: str) -> list[dict]:
    """Non-merge commits over this release's own range, newest first, parsed.

    The range ends at `new_tag` when that tag exists and at HEAD when it does
    not. Both cases are real: on the release PR the tag has not been created yet
    and HEAD *is* the release candidate, while re-running on master after the
    release must not sweep in everything merged since — which is what ending at
    HEAD unconditionally would do.
    """
    try:
        git("rev-parse", "--verify", f"{prev_tag}^{{commit}}")
    except Bail as exc:
        raise Bail(
            f"previous tag {prev_tag!r} is not in this repository — the section "
            f"header names a range that cannot be read, so the entries cannot be "
            f"rebuilt from it. ({exc})"
        ) from exc

    try:
        git("rev-parse", "--verify", f"{new_tag}^{{commit}}")
        tip = new_tag
    except Bail:
        tip = "HEAD"

    # `%x1f` / `%x1e` are git's own escapes — expanded by git into the output.
    # Writing the separator bytes into the format string instead would put a NUL
    # in argv, which execve rejects outright.
    raw = git("log", f"{prev_tag}..{tip}", "--no-merges",
              "--format=%H%x1f%s%x1f%b%x1e")
    out = []
    for chunk in raw.split("\x1e"):
        chunk = chunk.strip("\n")
        if not chunk.strip():
            continue
        sha, subject, body = (chunk.split("\x1f") + ["", "", ""])[:3]
        m = CONVENTIONAL_RE.match(subject.strip())
        if not m:
            continue                      # not conventional -> release-please ignores it
        if m.group("breaking") or BREAKING_FOOTER_RE.search(body):
            raise Bail(
                f"commit {sha[:7]} is a breaking change. release-please renders "
                "those in a '⚠ BREAKING CHANGES' block this tool does not model. "
                "Fix the section by hand for this release."
            )
        out.append({"sha": sha.strip(), "type": m.group("type"),
                    "scope": m.group("scope"), "desc": m.group("desc").strip()})
    return out


def render(commits: list[dict], visible: dict[str, str], order: list[str],
           base_url: str) -> list[str]:
    """release-please's exact bullet format, grouped and ordered like its config."""
    grouped: dict[str, list[dict]] = {}
    for c in commits:
        section = visible.get(c["type"])
        if section is None:
            continue                      # hidden or unknown type
        grouped.setdefault(section, []).append(c)

    lines: list[str] = []
    for section in order:
        if section not in grouped:
            continue
        # Two blank lines before each heading — release-please's exact shape.
        # Emitting one made this rewrite already-correct files just to delete a
        # newline, which is churn that trains people to ignore it.
        lines += ["", "", f"### {section}", ""]
        for c in grouped[section]:
            scope = f"**{c['scope']}:** " if c["scope"] else ""
            short = c["sha"][:7]
            lines.append(
                f"* {scope}{c['desc']} "
                f"([{short}]({base_url}/commit/{c['sha']}))"
            )
    return lines


def rebuild(text: str) -> tuple[str, str]:
    """Return (new_text, human_summary_of_change)."""
    lines = text.splitlines()
    start = next((i for i, ln in enumerate(lines) if SECTION_RE.match(ln)), None)
    if start is None:
        raise Bail("no '## [version](...compare/...)' section found in the changelog")

    header = SECTION_RE.match(lines[start])
    end = next((i for i in range(start + 1, len(lines))
                if lines[i].startswith("## [")), len(lines))

    visible, order = sections_from_config()
    body = lines[start + 1:end]
    for ln in body:
        h = HEADING_RE.match(ln)
        if h and h.group("name") not in order:
            raise Bail(
                f"section contains the heading {h.group('name')!r}, which is not a "
                "configured changelog section. This tool only rewrites sections it "
                "can regenerate exactly. Fix this release by hand."
            )

    commits = commits_in_range(header.group("prev"), header.group("new"))
    rebuilt = render(commits, visible, order, header.group("base"))
    new_body = rebuilt + [""]

    # Normalise trailing blank lines on both sides before comparing.
    def trimmed(xs: list[str]) -> list[str]:
        ys = list(xs)
        while ys and not ys[-1].strip():
            ys.pop()
        return ys

    if trimmed(body) == trimmed(new_body):
        return text, ""

    before = [ln for ln in body if ln.startswith("* ")]
    after = [ln for ln in new_body if ln.startswith("* ")]
    summary = (f"{len(before)} entr{'y' if len(before) == 1 else 'ies'} -> "
               f"{len(after)}; " + "; ".join(
                   [f"removed: {ln.strip()[:70]}" for ln in before if ln not in after]
                   + [f"added: {ln.strip()[:70]}" for ln in after if ln not in before]
               ))
    out = lines[:start + 1] + new_body + lines[end:]
    return "\n".join(out) + ("\n" if text.endswith("\n") else ""), summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true",
                    help="exit 1 if the changelog would change; write nothing")
    args = ap.parse_args()

    text = CHANGELOG.read_text()
    try:
        new_text, summary = rebuild(text)
    except Bail as exc:
        print(f"::error::changelog_dedup bailed out: {exc}")
        return 2

    if not summary:
        print("changelog matches the commits — nothing to do")
        return 0

    print(f"changelog disagrees with the commits: {summary}")
    if args.check:
        print("::error::run `python tools/changelog_dedup.py` and commit the result")
        return 1
    CHANGELOG.write_text(new_text)
    print("rewrote the newest section from the commits")
    return 0


if __name__ == "__main__":
    sys.exit(main())
