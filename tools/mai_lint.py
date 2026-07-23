#!/usr/bin/env python3
"""mai_lint.py — deterministic linter for @markdownai (mai) documents.

Takes the "read the doc and check it by hand" job off the model. Given files
or directories, it validates every @markdownai document it finds and exits
non-zero if any check fails, so it can run in a hook, a pre-commit, or CI.

What it catches (each maps to a real parser sharp edge):
  * frontmatter present, valid YAML, and schema-valid (markdownai.schema.json)
  * first body line is a `@markdownai vN` header
  * `@constraint:` colon form — the parser's regex needs whitespace after
    @constraint, so the colon form is silently DROPPED (willow-mcp #156)
  * greedy @constraint capture swallowing following content (#156)
  * a `@phase`/`@macro` line hiding inside YAML frontmatter — the phase tools
    parse the raw file so they'd see it, but the renderer never does (#157)
  * unbalanced @if/@endif, @macro/@endmacro, @prompt/@end

Usage:
  mai_lint.py                 # lint the default willow-mcp mai targets
  mai_lint.py FILE...         # lint specific files
  mai_lint.py DIR...          # walk dirs for @markdownai .md files
  mai_lint.py --quiet ...     # only print failures + summary

Exit code: 0 = all clean, 1 = at least one FAIL, 2 = bad invocation.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

try:
    import yaml
    import jsonschema
except ImportError as e:  # loud, not silent: say exactly what to install
    sys.stderr.write(f"[mai_lint] missing dependency: {e}. pip install pyyaml jsonschema\n")
    sys.exit(2)

REPO = Path(__file__).resolve().parent.parent
SCHEMA_PATH = REPO / "docs" / "schema" / "markdownai.schema.json"

# When no paths are given, lint the mai surface that ships with willow-mcp.
DEFAULT_TARGETS = [
    REPO / "docs" / "templates",
    REPO / "src" / "willow_mcp" / "bundle" / "templates",
    REPO / "skills",
]

FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
HEADER_RE = re.compile(r"^@markdownai\s+v\d+(\.\d+)*\s*$")
# The parser's own constraint regex, reproduced so the linter fails on exactly
# what the parser would silently mis-handle.
CONSTRAINT_RE = re.compile(
    r"@constraint(?:\s+severity=[\"']?(\w+)[\"']?)?\s+(.*?)(?=@constraint|$)", re.DOTALL
)


def _load_schema():
    try:
        return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))
    except OSError as e:
        sys.stderr.write(f"[mai_lint] cannot read schema {SCHEMA_PATH}: {e}\n")
        sys.exit(2)


def _is_mai(text: str) -> bool:
    m = FM_RE.match(text)
    body = m.group(2) if m else text
    for ln in body.splitlines():
        if ln.strip():
            return bool(HEADER_RE.match(ln.strip()))
    return False


def _iter_targets(paths):
    for p in paths:
        p = Path(p)
        if p.is_dir():
            for md in sorted(p.rglob("*.md")):
                try:
                    if _is_mai(md.read_text(encoding="utf-8", errors="replace")):
                        yield md
                except OSError:
                    continue
        elif p.is_file():
            yield p
        else:
            sys.stderr.write(f"[mai_lint] not found: {p}\n")


def lint_file(path: Path, schema, quiet: bool) -> bool:
    """Return True if the file passes every check."""
    text = path.read_text(encoding="utf-8", errors="replace")
    fails: list[str] = []
    warns: list[str] = []

    # Frontmatter is OPTIONAL per the spec: markdownai.schema.json has no
    # `required`, and the parser strips frontmatter "if any" then treats the
    # body as mai. A frontmatter-less doc is valid (the human-facing store docs
    # use exactly this form) — so its absence is not a failure; we just skip the
    # schema/frontmatter checks that have nothing to validate.
    m = FM_RE.match(text)
    fm_raw, body = (m.group(1), m.group(2)) if m else ("", text)

    if fm_raw:
        try:
            fm = yaml.safe_load(fm_raw)
            try:
                jsonschema.validate(fm, schema)
            except jsonschema.ValidationError as e:
                fails.append(f"frontmatter fails schema: {e.message}")
        except yaml.YAMLError as e:
            fails.append(f"frontmatter YAML parse error: {e}")

        # #157: a @phase/@macro hiding in frontmatter — phase tools would see it,
        # renderer would not.
        for hidden in ("@phase", "@macro"):
            if re.search(rf"^{hidden}\b", fm_raw, re.MULTILINE):
                fails.append(f"{hidden} appears inside frontmatter (invisible to the "
                             "renderer, but the phase/macro tools parse raw — #157)")

    # header is first non-blank body line. The parser accepts a bare
    # `@markdownai` (it matches on the prefix), so a version-less header is
    # tolerated — but the convention is `@markdownai vN` and the version carries
    # the compat signal, so flag it as a warning, not a failure.
    first = next((ln.strip() for ln in body.splitlines() if ln.strip()), None)
    if first and HEADER_RE.match(first):
        pass
    elif first and first.startswith("@markdownai"):
        warns.append(f"header has no version — use `@markdownai vN` (got {first!r})")
    else:
        fails.append(f"first body line is not a @markdownai header: {first!r}")

    # #156: colon form silently dropped
    n_colon = len(re.findall(r"@constraint:", body))
    if n_colon:
        fails.append(f"{n_colon}x `@constraint:` colon form — silently dropped by "
                     "the parser (needs whitespace after @constraint — #156)")

    # #156: the last @constraint's non-greedy capture only stops at EOF, so it
    # eats everything after it. A multi-line rule body (bullets/prose) is fine —
    # that is the author's intent. It is a real defect only when the tail
    # contains STRUCTURAL content (another @directive or a markdown heading)
    # that was meant to render on its own and is now buried inside the rule.
    cons = list(CONSTRAINT_RE.finditer(body))
    if cons:
        trailing = [l for l in cons[-1].group(2).strip().splitlines()[1:] if l.strip()]
        structural = [l for l in trailing
                      if l.lstrip().startswith("@") or re.match(r"^#{1,6}\s", l)]
        if structural:
            fails.append(f"last @constraint swallows structural content that will "
                         f"not render: {structural[0].strip()!r} (#156)")

    # @phase has no closing tag either — the last @phase captures to EOF. Each
    # @phase is placed before its own `## N` section, so the last phase's tail
    # should contain exactly ONE top-level (H2) heading (its own). A SECOND H2
    # means an appended sibling section (e.g. a trailing `## Constraints` from
    # the constraint-duplicate pattern) got silently buried inside the last
    # phase. Give that section its own @phase, or place it before the phases.
    phases = list(re.finditer(r"^@phase\b.*$", body, re.M))
    if phases:
        tail = body[phases[-1].end():]
        h2 = [ln for ln in tail.splitlines() if re.match(r"^##[ \t]", ln)]
        if len(h2) > 1:
            fails.append(f"last @phase swallows an appended section: {h2[1].strip()!r} "
                         "— give it its own @phase or move it before the phases "
                         "(@phase has no close; it captures to EOF)")

    # balanced blocks
    for open_tok, close_tok in (("@if", "@endif"), ("@macro", "@endmacro")):
        o = len(re.findall(rf"^{open_tok}\b", body, re.MULTILINE))
        c = len(re.findall(rf"^{close_tok}\b", body, re.MULTILINE))
        if o != c:
            fails.append(f"unbalanced {open_tok} ({o}) / {close_tok} ({c})")
    p_open = len(re.findall(r"^@prompt\b", body, re.MULTILINE))
    p_close = len(re.findall(r"^@end\s*$", body, re.MULTILINE))
    if p_open and p_open != p_close:
        warns.append(f"{p_open} @prompt vs {p_close} @end")

    _emit(path, fails, warns, quiet)
    return not fails


def _emit(path, fails, warns, quiet):
    if fails:
        print(f"FAIL {path}")
        for f in fails:
            print(f"     ✗ {f}")
    elif not quiet:
        print(f"ok   {path}")
    for w in warns:
        print(f"     ⚠ {w}")


def main(argv):
    quiet = "--quiet" in argv
    paths = [a for a in argv if not a.startswith("-")]
    targets = list(_iter_targets(paths or DEFAULT_TARGETS))
    if not targets:
        sys.stderr.write("[mai_lint] no @markdownai documents found\n")
        return 2
    schema = _load_schema()
    passed = sum(lint_file(t, schema, quiet) for t in targets)
    failed = len(targets) - passed
    print(f"\n{passed}/{len(targets)} clean" + (f", {failed} FAILED" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
