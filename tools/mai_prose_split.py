#!/usr/bin/env python3
"""mai_prose_split.py — the prose/structure pass for converting hard (prose-heavy)
docs to @markdownai.

The mechanical bites (templates, skills, operational docs) converted cleanly
because they were already structured. The HARD docs — VISION, the Constitution,
design docs, story chapters — are mostly narrative, and the loop's failure mode
is forcing that narrative into directives. This tool does the judgment-light
half deterministically: it separates PROTECTED PROSE (leave as rendered body)
from DIRECTIVE CANDIDATES (imperative rules -> @constraint, ordered
articles/steps -> @phase, operator params / env -> @env, audience-switched
guidance -> @if consumer=...), and reports a prose_ratio + verdict so a doc that
is essentially a story is flagged "do not force" instead of being mangled.

Output is a conversion PLAN (JSON), not a converted doc: it is the scaffolding a
converting agent (or a human) works from, with the prose fenced off.

Usage:
  mai_prose_split.py FILE...            # JSON plan per file
  mai_prose_split.py --summary FILE...  # one-line verdict per file
  mai_prose_split.py DIR                # all .md under DIR
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

FM_RE = re.compile(r"\A---\n(.*?)\n---\n(.*)\Z", re.DOTALL)
HEADER_RE = re.compile(r"^@markdownai\s+v\d", re.M)

# Imperative rule → @constraint candidate.
RULE_RE = re.compile(
    r"^\s*(?:[-*]\s+)?(?:\*\*)?"
    r"(Must|Must not|Never|Always|Do not|Don't|Shall|Shall not|May not|"
    r"No\s+\w+|It is forbidden|Required:|MUST|SHALL|NEVER)\b",
)
RULE_INLINE_RE = re.compile(r"\b(must not|shall not|may not|is forbidden|never\b)", re.I)
# Ordered / articled section → @phase candidate.
PHASE_HEAD_RE = re.compile(
    r"^#{1,4}\s+(?:(Article|Step|Phase|Stage)\b|(\d+)\.\s)", re.I)
TRACE_ID_RE = re.compile(r"\b([A-Z]{3,}-[0-9IVXLC]+(?:-\d+)?)\b")  # CONST-0, CONST-I-1
# Operator parameter / env → @env candidate.
PARAM_RE = re.compile(r"\(proposed default[^)]*operator-adjustable[^)]*\)", re.I)
ENV_RE = re.compile(r"\b([A-Z][A-Z0-9]{2,}(?:_[A-Z0-9]+)+)\b")  # WILLOW_HOME
PATH_RE = re.compile(r"(~?/[\w./~-]*\.willow[\w./-]*|~/\.\w[\w./-]*)")
# Audience-switched guidance → @if consumer=...
AUDIENCE_RE = re.compile(
    r"\b(for agents?:|for humans?:|agents? should|human operators?|"
    r"if you are an? (?:ai|agent)|for the operator:)", re.I)

HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")


def _split_fm(text):
    m = FM_RE.match(text)
    return (m.group(1), m.group(2)) if m else ("", text)


def _blocks(body):
    """Yield (start_line, [lines]) prose/element blocks separated by blank lines."""
    lines = body.splitlines()
    buf, start = [], 0
    for i, ln in enumerate(lines):
        if ln.strip() == "":
            if buf:
                yield start, buf
                buf = []
            continue
        if not buf:
            start = i + 1
        buf.append(ln)
    if buf:
        yield start, buf


def _propose_frontmatter(body):
    h1 = next((m.group(2) for ln in body.splitlines()
               if (m := HEADING_RE.match(ln)) and len(m.group(1)) == 1), None)
    # first prose sentence as description
    desc = ""
    for _, blk in _blocks(body):
        joined = " ".join(blk).lstrip("> *")
        if not joined.startswith(("@", "#", "|", "-", "```")):
            desc = re.sub(r"\s+", " ", joined)[:160]
            break
    name = (h1 or "").strip().lower()
    name = re.sub(r"[^a-z0-9]+", "-", name).strip("-")
    return {"kind": "doc", "name": name or "untitled", "description": desc or h1 or ""}


def classify(path: Path):
    text = path.read_text(encoding="utf-8", errors="replace")
    fm, body = _split_fm(text)
    segs = []
    counts = {"constraint": 0, "phase": 0, "env": 0, "if": 0, "prose": 0}

    for start, blk in _blocks(body):
        joined = "\n".join(blk)
        first = blk[0]
        kind = "prose"
        proposed = None

        if PHASE_HEAD_RE.search(first) or TRACE_ID_RE.search(first):
            kind = "phase"
            tid = TRACE_ID_RE.search(first)
            nm = HEADING_RE.match(first)
            label = (nm.group(2) if nm else first).strip()
            proposed = f"@phase {tid.group(1) if tid else re.sub(r'[^a-z0-9]+','-',label.lower()).strip('-')}"
        elif RULE_RE.search(first) or (first.lstrip().startswith(("-", "*")) and RULE_INLINE_RE.search(joined)):
            kind = "constraint"
            sev = "critical" if re.search(r"\b(never|must not|shall not|forbidden)\b", joined, re.I) else "normal"
            proposed = f'@constraint severity="{sev}"'
        elif AUDIENCE_RE.search(joined):
            kind = "if"
            aud = "ai" if re.search(r"agent|ai", first, re.I) else "human"
            proposed = f'@if consumer="{aud}"'
        elif PARAM_RE.search(joined):
            kind = "env"
            proposed = "@env  # operator-adjustable parameter"

        # collect env/param signals even inside prose (annotate, don't reclassify)
        envs = sorted(set(ENV_RE.findall(joined)) - {"ΔΣ"})
        paths = PATH_RE.findall(joined)
        params = PARAM_RE.findall(joined)

        counts[kind] += 1
        seg = {"kind": kind, "line": start, "head": first[:90]}
        if proposed:
            seg["proposed"] = proposed
        if envs or paths or params:
            seg["signals"] = {"env": envs[:6], "paths": paths[:4], "operator_params": len(params)}
        segs.append(seg)

    directive_blocks = counts["constraint"] + counts["phase"] + counts["env"] + counts["if"]
    total = max(1, directive_blocks + counts["prose"])
    prose_ratio = round(counts["prose"] / total, 2)
    if prose_ratio >= 0.85:
        verdict = "NARRATIVE — protect. frontmatter + prose only; do NOT force directives."
    elif prose_ratio >= 0.55:
        verdict = "prose-led — thin directive layer (lift the few real rules/phases; keep the rest prose)."
    else:
        verdict = "structured — rich directive layer is safe."

    return {
        "doc": str(path),
        "has_frontmatter": bool(fm),
        "has_header": bool(HEADER_RE.search(body)),
        "proposed_frontmatter": None if fm else _propose_frontmatter(body),
        "prose_ratio": prose_ratio,
        "verdict": verdict,
        "counts": counts,
        "segments": segs,
    }


def _iter(paths):
    for p in map(Path, paths):
        if p.is_dir():
            yield from sorted(p.rglob("*.md"))
        elif p.is_file():
            yield p
        else:
            sys.stderr.write(f"[mai_prose_split] not found: {p}\n")


def main(argv):
    summary = "--summary" in argv
    paths = [a for a in argv if not a.startswith("-")]
    if not paths:
        sys.stderr.write(__doc__)
        return 2
    plans = [classify(p) for p in _iter(paths)]
    if summary:
        for pl in plans:
            c = pl["counts"]
            print(f"{pl['prose_ratio']:>4}  {pl['verdict'].split(' —')[0]:<12} "
                  f"C{c['constraint']} P{c['phase']} E{c['env']} I{c['if']} "
                  f"prose{c['prose']}  {pl['doc']}")
    else:
        print(json.dumps(plans if len(plans) > 1 else plans[0], indent=1, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
