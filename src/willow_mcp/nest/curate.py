"""
nest-seed/curate.py — curate the auto-discovered categories.

promote_clusters() (selflearn.py) coins categories with machine names like
`auto:seed-version-1-0`. They're real clusters but the names are noise, and some
clusters are pure artifact (export boilerplate, file headers). This module is the
human gate: list what was discovered, give the keepers real names, prune the junk.

Curation touches two surfaces and keeps them in sync:
  - the discovered-category store (`discovered_{model}.json`) — drives *future*
    classification, so renames/prunes here change what new files match.
  - the existing fragment labels in the canonical DB — so the digest, --ask, and
    the bridge reflect the curated names *now*, not the machine ones.

A rename moves the store entry under a new name (kept under DISCOVERED_PREFIX so
provenance stays visible) and relabels every fragment carrying the old label. A
prune drops the store entry and clears the label on its fragments (the fragments
survive — only the junk category goes). Pure stdlib + sqlite; no model calls.
"""
from __future__ import annotations

import sqlite3

try:  # works both as a package (apps.nest_seed) and as a plain script dir
    from . import selflearn as _learn
    from . import embed as _embed
except ImportError:
    import selflearn as _learn
    import embed as _embed


def _normalize_name(new: str) -> str:
    """Keep curated names under the auto: namespace so provenance stays visible."""
    new = new.strip()
    if not new:
        return ""
    return new if new.startswith(_learn.DISCOVERED_PREFIX) else _learn.DISCOVERED_PREFIX + new


def _db_label_counts(db_path: str) -> dict[str, int]:
    try:
        conn = sqlite3.connect(str(db_path))
        rows = conn.execute(
            "select label, count(*) from fragments where label != '' group by label"
        ).fetchall()
        conn.close()
    except sqlite3.Error:
        return {}
    return {lbl: n for lbl, n in rows}


def list_categories(db_path: str, model: str = _embed.DEFAULT_EMBED_MODEL) -> dict:
    """Discovered categories with their store metadata and live DB fragment counts."""
    disc = _learn.load_discovered(model)
    db_counts = _db_label_counts(db_path)
    out = []
    for name, e in sorted(disc.items(), key=lambda kv: -kv[1].get("size", 0)):
        out.append({
            "name": name,
            "size": e.get("size", 0),
            "cohesion": e.get("cohesion"),
            "representative": (e.get("label") or "")[:100],
            "db_fragments": db_counts.get(name, 0),
        })
    return {"status": "ok", "model": model, "count": len(out), "categories": out}


def _relabel_fragments(db_path: str, old: str, new: str) -> int:
    """Set label `new` (or '' to clear) on every fragment currently labelled `old`."""
    try:
        conn = sqlite3.connect(str(db_path))
        cur = conn.execute("update fragments set label=? where label=?", (new, old))
        conn.commit()
        n = cur.rowcount
        conn.close()
    except sqlite3.Error:
        return 0
    return n


def rename_category(db_path: str, old: str, new: str,
                    model: str = _embed.DEFAULT_EMBED_MODEL) -> dict:
    """Rename a discovered category in the store and relabel its DB fragments."""
    disc = _learn.load_discovered(model)
    if old not in disc:
        return {"status": "error", "reason": f"unknown category: {old}"}
    new_name = _normalize_name(new)
    if not new_name:
        return {"status": "error", "reason": "new name is empty"}
    if new_name != old and new_name in disc:
        return {"status": "error", "reason": f"target already exists: {new_name}"}

    entry = disc.pop(old)
    disc[new_name] = entry
    _learn.save_discovered(model, disc)
    relabelled = _relabel_fragments(db_path, old, new_name)
    return {"status": "ok", "old": old, "new": new_name, "fragments_relabelled": relabelled}


def prune_category(db_path: str, name: str,
                   model: str = _embed.DEFAULT_EMBED_MODEL) -> dict:
    """Drop a discovered category from the store and clear its fragment labels."""
    disc = _learn.load_discovered(model)
    if name not in disc:
        return {"status": "error", "reason": f"unknown category: {name}"}
    disc.pop(name)
    _learn.save_discovered(model, disc)
    cleared = _relabel_fragments(db_path, name, "")
    return {"status": "ok", "pruned": name, "fragments_cleared": cleared}
