"""
nest-seed/bridge.py — the L1→fleet bridge (PII-safe).

`~/Desktop/Nest` is the local-only PII zone. The Nest DB holds a person's legal
filings, messages, journals — content that must never leave this machine. So the
bridge does NOT push fragment content into the fleet KB. It pushes *structure*:
the shape of the Nest — how many sources, what categories the classifier and the
operator's curation settled on, how big each is, and that N credentials were
found and redacted. Counts and curated category names, not the words inside.

That asymmetry is the whole point. The fleet learns "this operator keeps a large
legal/co-parenting archive and a reading list, and there are 3 unrotated secrets"
— enough to be useful, nothing that leaks. Curation (curate.py) is the gate: the
operator renames/prunes the auto: categories *before* their names bridge out.

The app stays portable — it emits a manifest of KB-ingestable atoms to a sidecar
(`<db>.bridge.json`) and prints them. The fleet agent (which has kb_ingest) reads
the manifest and ingests, mem_check-gated. The app itself has no MCP dependency.
"""
from __future__ import annotations

import json
import os
import sqlite3

try:  # works as a package or a plain script dir
    from . import selflearn as _learn
    from . import embed as _embed
    from . import digest as _digest
except ImportError:
    import selflearn as _learn
    import embed as _embed
    import digest as _digest

# Topical categories the bridge summarises (same set the digest treats as topical).
_TOPICAL = ("document", "note", "receipt")


def _owner(conn: sqlite3.Connection) -> str:
    try:
        row = conn.execute("select owner from nest_meta where id=1").fetchone()
        return (row[0] if row else "") or "unknown"
    except sqlite3.Error:
        return "unknown"


def build_bridge(db_path: str, model: str = _embed.DEFAULT_EMBED_MODEL) -> dict:
    """Build a PII-safe set of fleet-KB atoms describing the Nest's structure.

    Returns {status, owner, atoms:[{title,summary,category,tags,keywords,source_id}]}.
    No fragment content, filenames, person names, or secret values are included —
    only counts, curated category names, and redacted secret *kinds*.
    """
    conn = sqlite3.connect(str(db_path))
    q = lambda s, *a: conn.execute(s, a).fetchall()

    src_total = q("select count(*) from sources")[0][0]
    frag_total = q("select count(*) from fragments")[0][0]
    raw_cats = q(f"""select label, count(*) n from fragments
                 where label != '' and fragment_type in
                 ({','.join('?' for _ in _TOPICAL)})
                 group by label order by n desc""", *_TOPICAL)
    # THE WALL: a fragment's label is a topical category only when it came from
    # the embedding/LLM tier; the regex fallback labels it with its *filename*,
    # which embeds dates and names. Only allowlisted category names (never a
    # filename) may cross into a KB atom — the rest are counted as uncategorised,
    # honestly, not silently dropped.
    cats = [(lbl, n) for lbl, n in raw_cats if _digest.is_category_name(lbl)]
    uncategorised = sum(n for lbl, n in raw_cats if not _digest.is_category_name(lbl))
    secret_kinds = q("select label, count(*) from fragments "
                     "where fragment_type='secret' group by label order by 2 desc")
    owner = _owner(conn)
    conn.close()

    disc = _learn.load_discovered(model)
    safe_owner = owner.lower().replace(" ", "-")
    atoms: list[dict] = []

    # 1) Overview atom — the shape of the whole Nest, counts only.
    cat_line = ", ".join(f"{lbl} ({n})" for lbl, n in cats[:8]) or "uncategorised"
    uncat_line = f" {uncategorised} uncategorised (filename-labelled)." if uncategorised else ""
    atoms.append({
        "title": f"Nest structure: {owner}",
        "summary": (
            f"{owner}'s local Nest holds {src_total} sources / {frag_total:,} "
            f"fragments (local-only PII zone; content stays on-device). Topical "
            f"categories by size: {cat_line}.{uncat_line} {len(disc)} auto-discovered "
            f"category clusters. Source: nest-seed bridge (structure only, no content)."
        ),
        "category": "nest",
        "tags": ["nest", "structure", "personal-data", safe_owner],
        "keywords": ["nest", "nest-seed", "bridge", owner],
        "source_id": f"nest:{safe_owner}:structure",
    })

    # 2) One atom per topical category — name + count + generic description.
    for lbl, n in cats:
        desc = _digest._CATMAP.get(lbl, "")
        coh = disc.get(lbl, {}).get("cohesion")
        coh_s = f", cohesion {coh}" if coh is not None else ""
        atoms.append({
            "title": f"Nest category · {owner} · {lbl}",
            "summary": (f"{n} fragments in {owner}'s Nest classified as '{lbl}'"
                        f"{(' — ' + desc) if desc else ''}{coh_s}. Structure only."),
            "category": "nest",
            "tags": ["nest", "category", safe_owner, lbl],
            "keywords": ["nest", lbl, owner],
            "source_id": f"nest:{safe_owner}:cat:{lbl}",
        })

    # 3) Security atom — flags unrotated credentials to the fleet (kinds, not values).
    if secret_kinds:
        total_s = sum(n for _, n in secret_kinds)
        kinds = ", ".join(f"{k} ({n})" for k, n in secret_kinds)
        atoms.append({
            "title": f"Nest security: {total_s} redacted credentials — {owner}",
            "summary": (f"nest-seed's guard found and redacted {total_s} credential(s) "
                        f"in {owner}'s Nest: {kinds}. Values are redacted in the DB; the "
                        f"live source files/credentials still need operator rotation."),
            "category": "nest",
            "tags": ["nest", "security", "secrets", "action-required", safe_owner],
            "keywords": ["nest", "secret", "rotate", "credential", owner],
            "source_id": f"nest:{safe_owner}:security",
        })

    return {"status": "ok", "owner": owner, "model": model,
            "sources": src_total, "fragments": frag_total, "atoms": atoms}


def write_manifest(db_path: str, model: str = _embed.DEFAULT_EMBED_MODEL) -> dict:
    """Build the bridge and persist it to a sidecar next to the DB."""
    res = build_bridge(db_path, model)
    path = f"{db_path}.bridge.json"
    try:
        with open(path, "w") as f:
            json.dump(res, f, indent=2)
        res["manifest"] = path
    except OSError as e:
        res["manifest_error"] = str(e)
    return res
