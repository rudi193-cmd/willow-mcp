"""
sap/code_graph/fuzzy.py — Fuzzy symbol search + file suggestion.

Port of fuzzy.ts from budget-aware-mcp. Tiered matching:
  exact name → prefix → contains → camelCase/snake_case token split.

suggest_files() ranks files by keyword overlap with a task description —
no embeddings, pure token intersection + symbol name scoring.
"""
from __future__ import annotations

import re
import sqlite3
from pathlib import Path


# ── Identifier splitting ──────────────────────────────────────────────────────

def _split_identifier(name: str) -> list[str]:
    """Split camelCase / snake_case into lowercase tokens."""
    parts = re.split(r"[_\-./\\]", name)
    all_parts: list[str] = []
    for part in parts:
        # Split camelCase: authService → auth service
        camel = re.sub(r"([a-z])([A-Z])", r"\1 \2", part).split()
        all_parts.extend(camel)
    return [p.lower() for p in all_parts if len(p) > 1]


def _keywords(text: str) -> list[str]:
    """Extract meaningful lowercase keywords from arbitrary text."""
    raw = re.findall(r"[A-Za-z][A-Za-z0-9_]*", text)
    stop = {"the", "a", "an", "of", "to", "in", "for", "and", "or",
            "is", "it", "at", "by", "as", "on", "be", "do", "we",
            "that", "this", "with", "from", "use", "used", "get", "set",
            "def", "class", "import", "return", "if", "else", "not"}
    return [w.lower() for w in raw if len(w) > 2 and w.lower() not in stop]


def _dedupe(rows: list[dict], key: str, limit: int) -> list[dict]:
    seen: set = set()
    out: list[dict] = []
    for r in rows:
        k = r.get(key)
        if k not in seen:
            seen.add(k)
            out.append(r)
            if len(out) >= limit:
                break
    return out


# ── Symbol search ─────────────────────────────────────────────────────────────

def search_symbols(
    db_path: str | Path,
    query: str,
    *,
    max_results: int = 20,
    kinds: list[str] | None = None,
) -> list[dict]:
    """Fuzzy symbol search: exact → prefix → contains → token-split match."""
    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row

    kind_clause = ""
    kind_params: list = []
    if kinds:
        placeholders = ",".join("?" * len(kinds))
        kind_clause = f" AND kind IN ({placeholders})"
        kind_params = list(kinds)

    lq = query.lower()
    results: list[dict] = []

    def _fetch(where: str, params: list) -> list[dict]:
        sql = (
            "SELECT name, fqn, kind, file_path, start_line, end_line, signature "
            f"FROM symbols WHERE {where}{kind_clause} ORDER BY name LIMIT ?"
        )
        rows = conn.execute(sql, params + kind_params + [max_results]).fetchall()
        return [dict(r) for r in rows]

    # 1. Exact name match
    results += _fetch("LOWER(name) = ?", [lq])
    if len(results) >= max_results:
        conn.close()
        return _dedupe(results, "fqn", max_results)

    # 2. Prefix match
    results += _fetch("LOWER(name) LIKE ?", [f"{lq}%"])

    # 3. Contains match on name or fqn
    results += _fetch("(LOWER(name) LIKE ? OR LOWER(fqn) LIKE ?)", [f"%{lq}%", f"%{lq}%"])

    # 4. Token-split: match any token from the query
    tokens = _split_identifier(query)
    for token in tokens:
        if len(token) < 3:
            continue
        results += _fetch("LOWER(name) LIKE ?", [f"%{token}%"])

    conn.close()
    return _dedupe(results, "fqn", max_results)


# ── explain_symbol ────────────────────────────────────────────────────────────

def explain_symbol(db_path: str | Path, name: str) -> dict:
    """Return signature, location, callers (inbound import/inherit edges),
    and callees (outbound) for the best-matching symbol."""
    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row

    # Best match: prefer exact fqn or name
    row = (
        conn.execute("SELECT * FROM symbols WHERE fqn = ?", (name,)).fetchone()
        or conn.execute("SELECT * FROM symbols WHERE name = ? ORDER BY kind", (name,)).fetchone()
        or conn.execute("SELECT * FROM symbols WHERE name LIKE ? ORDER BY kind LIMIT 1",
                        (f"%{name}%",)).fetchone()
    )
    if not row:
        conn.close()
        return {"error": f"symbol not found: {name!r}"}

    sym = dict(row)

    callers = conn.execute(
        "SELECT source_fqn, edge_type FROM edges WHERE target_fqn = ? LIMIT 20",
        (sym["fqn"],),
    ).fetchall()
    callees = conn.execute(
        "SELECT target_fqn, edge_type FROM edges WHERE source_fqn = ? LIMIT 20",
        (sym["fqn"],),
    ).fetchall()

    conn.close()
    return {
        "name":      sym["name"],
        "fqn":       sym["fqn"],
        "kind":      sym["kind"],
        "file_path": sym["file_path"],
        "start_line": sym["start_line"],
        "end_line":  sym["end_line"],
        "signature": sym["signature"],
        "callers":   [{"fqn": r[0], "via": r[1]} for r in callers],
        "callees":   [{"fqn": r[0], "via": r[1]} for r in callees],
    }


# ── suggest_files ─────────────────────────────────────────────────────────────

def suggest_files(
    db_path: str | Path,
    task: str,
    *,
    max_results: int = 10,
) -> list[dict]:
    """Rank files by keyword overlap with a task description.

    Scoring:
      +3 for each keyword that exactly matches a symbol name in that file
      +1 for each keyword found in the file path
    Returns list of {file_path, score, matching_symbols}.
    """
    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row

    kws = _keywords(task)
    if not kws:
        conn.close()
        return []

    file_scores: dict[str, int] = {}
    file_symbols: dict[str, list[str]] = {}

    for kw in kws:
        # Symbol name match
        rows = conn.execute(
            "SELECT file_path, name FROM symbols WHERE LOWER(name) LIKE ? AND kind != 'module'",
            (f"%{kw}%",),
        ).fetchall()
        for r in rows:
            fp = r["file_path"]
            file_scores[fp] = file_scores.get(fp, 0) + 3
            file_symbols.setdefault(fp, []).append(r["name"])

        # File path match
        fp_rows = conn.execute(
            "SELECT path FROM indexed_files WHERE LOWER(path) LIKE ?",
            (f"%{kw}%",),
        ).fetchall()
        for r in fp_rows:
            fp = r["path"]
            file_scores[fp] = file_scores.get(fp, 0) + 1

    conn.close()

    ranked = sorted(file_scores.items(), key=lambda x: -x[1])
    return [
        {
            "file_path": fp,
            "score": score,
            "matching_symbols": sorted(set(file_symbols.get(fp, [])))[:8],
        }
        for fp, score in ranked[:max_results]
    ]
