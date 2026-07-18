"""
nest-seed/digest.py — a one-page narrative map of a seeded Nest DB.

Reads sources + fragments (and the discovered-category store) and renders a
Markdown digest: what the dump *is*, category breakdown, auto-discovered
clusters, the people who show up, a timeline, biggest sources, and how files
were read. Pure stdlib + sqlite — no model calls, deterministic.
"""
from __future__ import annotations

import os
import re
import sqlite3
from collections import Counter

try:  # works as a package or a plain script dir
    from . import selflearn as _learn
    from . import embed as _embed
except ImportError:
    import selflearn as _learn
    import embed as _embed

_CATMAP = {
    "data": "structured data (JSON/CSV exports, DB dumps)",
    "education": "lesson plans & curricula",
    "legal": "legal / disclosure / filings",
    "knowledge": "explainers & docs",
    "specs": "design/spec docs",
    "config": "config files",
    "code": "source code",
    "journal": "journal entries",
    "narrative": "stories / prose",
    "correspondence": "letters / email",
    "financial": "receipts / invoices",
    "personal": "personal / private notes",
    "other": "misc",
}

# The topical category names that are allowed to cross the wall. A fragment's
# `label` is a topical category ONLY when it was classified by the embedding/LLM
# tier; the regex fallback labels document/receipt fragments with their
# *filename* instead — and a filename embeds dates and names, exactly what the
# wall exists to keep out of the digest and the KB bridge. So a label is treated
# as a category only if it is a known topical name or a curated discovered one
# (auto: prefix); anything else (a filename) is not a category and is dropped.
_ALLOWED_CATEGORIES = frozenset(_CATMAP) | {"media"}


def is_category_name(label: str) -> bool:
    """True if `label` may cross the wall as a category name (never a filename)."""
    return bool(label) and (
        label in _ALLOWED_CATEGORIES or label.startswith(_learn.DISCOVERED_PREFIX)
    )


# A genuine "Firstname Lastname" — the digest stays clean even if the DB isn't.
_NAME_RE = re.compile(r"^[A-Z][a-z]+ [A-Z][a-z]+$")
_YEAR_RE = re.compile(r"(19|20)\d{2}")


def build_digest(db_path: str, model: str = _embed.DEFAULT_EMBED_MODEL,
                 wall: bool = False) -> str:
    """Render a Markdown map of a seeded Nest DB.

    wall=False (default): the full local view — includes the people who show up,
    a date timeline, and source filenames. For the operator's own screen.

    wall=True: the walled view — structure only. Person names, the date
    timeline, and filenames are suppressed; counts, category breakdown,
    discovered clusters, and redacted secret *kinds* remain. This is what
    ``nest_digest`` returns over MCP: relative/structural shape is process
    (shareable); absolute content — a name, a date, a filename — is person
    (walled). Same seam as bridge.build_bridge and corpuslens's Guard.
    """
    conn = sqlite3.connect(str(db_path))
    q = lambda s, *a: conn.execute(s, a).fetchall()

    src_total = q("select count(*) from sources")[0][0]
    by_ocr = dict(q("select ocr_method,count(*) from sources where ocr_method!='' group by 1 order by 2 desc"))
    ftypes = dict(q("select fragment_type,count(*) from fragments group by 1 order by 2 desc"))
    cats = [(lbl, n) for lbl, n in q(
                """select label,count(*) n from fragments where label!='' and fragment_type in
                   ('document','note','receipt') group by 1 order by 2 desc""")
            if is_category_name(lbl)]  # filenames-as-labels never cross the wall
    names = Counter(v for (v,) in q("select content from fragments where fragment_type='person'")
                    if _NAME_RE.match(v))
    secrets = Counter(lbl for (lbl,) in q("select label from fragments where fragment_type='secret'"))
    dates = [d for (d,) in q("select date_ref from fragments where fragment_type='date' and date_ref!=''")]
    big = q("""select s.filename,count(*) n from fragments f join sources s on s.id=f.source_id
               group by 1 order by 2 desc limit 6""")
    conn.close()

    yrs = Counter(m.group() for d in dates for m in [_YEAR_RE.search(d)] if m)
    epoch = yrs.pop("1970", 0)
    frag_total = sum(ftypes.values())

    L = ["# 🪺 Nest Digest\n"]
    scope = ("structure only — names, dates, and filenames walled"
             if wall else "generated locally; nothing left this machine")
    L.append(f"_A map of `{os.path.dirname(db_path) or '.'}` — {src_total} sources, "
             f"{frag_total:,} fragments. {scope}._\n")

    # What it is
    top_cat = cats[0][0] if cats else "—"
    big_src = ", ".join(f"`{fn}`" for fn, _ in big[:2]) if big else "—"
    L.append("## What this is\n")
    if wall:
        L.append(f"Dates are {ftypes.get('date',0):,} of "
                 f"{frag_total:,} fragments; the dominant topical category is **{top_cat}**. "
                 f"Across {src_total} files the dump breaks down as below.\n")
    else:
        L.append(f"The largest sources are {big_src}. Dates are {ftypes.get('date',0):,} of "
                 f"{frag_total:,} fragments; the dominant topical category is **{top_cat}**. "
                 f"Across {src_total} files the dump breaks down as below.\n")

    if secrets:
        total_s = sum(secrets.values())
        L.append(f"## ⚠️ Secrets detected — {total_s}\n")
        L.append("Credentials found in the dump and stored **redacted**. Review and rotate:")
        for kind, n in secrets.most_common():
            L.append(f"- **{kind}** ({n})")
        L.append("")

    L.append("## By category\n")
    for label, n in cats:
        L.append(f"- **{label}** ({n}) — {_CATMAP.get(label, '')}")
    L.append("")

    disc = _learn.load_discovered(model)
    if disc:
        L.append("## Auto-discovered clusters\n")
        for name, e in sorted(disc.items(), key=lambda kv: -kv[1].get("size", 0)):
            L.append(f"- `{name}` — {e.get('size','?')} docs, cohesion {e.get('cohesion','?')}")
        L.append("")

    if names and not wall:
        L.append("## People who show up\n")
        L.append(", ".join(f"{n} ({k}×)" if k > 1 else n for n, k in names.most_common(15)))
        L.append("")

    if yrs and not wall:
        span = sorted(yrs)
        peak = max(yrs.values())
        L.append("## Timeline\n")
        L.append(f"Spans **{span[0]}–{span[-1]}**:")
        for y, n in sorted(yrs.items(), key=lambda x: -x[1])[:6]:
            bar = "█" * max(1, round(n / peak * 18))
            L.append(f"- {y}: {bar} {n}")
        if epoch:
            L.append(f"\n⚠️ plus **{epoch}** epoch-zero (`1970`) timestamps — null-date "
                     f"artifacts from a 0-ms export, not real events.")
        L.append("")

    if big and not wall:
        L.append("## Biggest sources\n")
        for fn, n in big:
            L.append(f"- `{fn}` — {n} fragments")
        L.append("")

    if by_ocr:
        L.append("## How it was read\n")
        L.append(", ".join(f"{m} ({n})" for m, n in by_ocr.items()))

    return "\n".join(L)
