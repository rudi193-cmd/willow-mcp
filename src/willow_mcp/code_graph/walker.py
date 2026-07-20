"""
sap/code_graph/walker.py — Budget-aware BFS graph walk.

Port of graph_walk.ts from budget-aware-mcp. Walks the symbol graph
outward from an anchor, collecting symbols until the token budget is hit.
Token estimate: symbol byte_size / 4 (conservative).
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path


@dataclass
class WalkResult:
    symbols: list[dict]
    files: list[str]
    hops_traversed: int
    tokens_returned: int
    anchor_fqn: str


def _resolve_anchor(conn: sqlite3.Connection, anchor: str) -> list[str]:
    """Find FQN(s) that match the anchor (exact name, then prefix, then substring)."""
    rows = conn.execute(
        "SELECT fqn FROM symbols WHERE fqn = ? OR name = ? ORDER BY fqn LIMIT 5",
        (anchor, anchor),
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    rows = conn.execute(
        "SELECT fqn FROM symbols WHERE name LIKE ? ORDER BY fqn LIMIT 5",
        (f"{anchor}%",),
    ).fetchall()
    if rows:
        return [r[0] for r in rows]

    rows = conn.execute(
        "SELECT fqn FROM symbols WHERE fqn LIKE ? OR name LIKE ? ORDER BY fqn LIMIT 5",
        (f"%{anchor}%", f"%{anchor}%"),
    ).fetchall()
    return [r[0] for r in rows]


def walk(
    db_path: str | Path,
    anchor: str,
    *,
    hop_depth: int = 2,
    max_tokens: int = 8_000,
    edge_types: tuple[str, ...] = ("import", "inherit"),
) -> WalkResult:
    """BFS from anchor symbol, collect context within token budget.

    Deterministic: symbols at each hop level sorted alphabetically.
    Edge direction: outgoing (source → target) for import, both directions
    for inherit so callers flow upward.
    """
    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row

    anchors = _resolve_anchor(conn, anchor)
    if not anchors:
        conn.close()
        return WalkResult(
            symbols=[], files=[], hops_traversed=0,
            tokens_returned=0, anchor_fqn=anchor,
        )

    visited: set[str] = set()
    collected_list: list[dict] = []
    tokens_used = 0
    hops_traversed = 0
    current_level = sorted(anchors)

    for hop in range(hop_depth + 1):
        if not current_level:
            break
        next_level: list[str] = []

        for fqn in current_level:
            if fqn in visited:
                continue
            visited.add(fqn)

            row = conn.execute(
                "SELECT name, fqn, kind, file_path, start_line, end_line, signature, byte_size "
                "FROM symbols WHERE fqn = ?",
                (fqn,),
            ).fetchone()
            if not row:
                continue

            token_cost = max(50, (row["byte_size"] or 0) // 4)
            if tokens_used + token_cost > max_tokens and collected_list:
                continue  # budget hit — skip this symbol but keep walking for next hop

            tokens_used += token_cost
            sym = dict(row)
            sym["hop_distance"] = hop
            collected_list.append(sym)

            if hop < hop_depth:
                # Import edges are indexed at module level — derive parent module fqn
                # e.g. sandbox.fleet.fleet_create → sandbox.fleet
                #      sandbox.fleet.FleetState.advance → sandbox.fleet
                fqn_parts = fqn.split(".")
                edge_sources = {fqn}
                if row["kind"] in ("function", "method", "class"):
                    # module is everything up to (but not including) the symbol name
                    # for method: drop last two segments; for function/class: drop last one
                    if row["kind"] == "method" and len(fqn_parts) > 2:
                        edge_sources.add(".".join(fqn_parts[:-2]))
                    if len(fqn_parts) > 1:
                        edge_sources.add(".".join(fqn_parts[:-1]))

                for src in edge_sources:
                    out_edges = conn.execute(
                        "SELECT target_fqn FROM edges WHERE source_fqn = ? AND edge_type IN ({})".format(
                            ",".join("?" * len(edge_types))
                        ),
                        (src, *edge_types),
                    ).fetchall()
                    next_level.extend(r[0] for r in out_edges)

                # Incoming inherit edges (callers/subclasses flow back)
                in_inherit = conn.execute(
                    "SELECT source_fqn FROM edges WHERE target_fqn = ? AND edge_type = 'inherit'",
                    (fqn,),
                ).fetchall()
                next_level.extend(r[0] for r in in_inherit)

        hops_traversed = hop
        current_level = sorted(set(next_level) - visited)

    conn.close()

    files = sorted({s["file_path"] for s in collected_list})
    return WalkResult(
        symbols=collected_list,
        files=files,
        hops_traversed=hops_traversed,
        tokens_returned=tokens_used,
        anchor_fqn=anchors[0],
    )


def analyze_impact(
    db_path: str | Path,
    file_paths: list[str],
    *,
    max_tokens: int = 6_000,
) -> dict:
    """Blast radius: what symbols import from the given files?

    For each file in file_paths, find all symbols defined there,
    then find all symbols that import from those modules.
    Returns affected files + symbols sorted by hop distance.
    """
    conn = sqlite3.connect(str(Path(db_path).expanduser()))
    conn.row_factory = sqlite3.Row

    # Collect module FQNs for the changed files
    source_modules: list[str] = []
    for fp in file_paths:
        rows = conn.execute(
            "SELECT DISTINCT fqn FROM symbols WHERE file_path = ? AND kind = 'module'",
            (fp,),
        ).fetchall()
        source_modules.extend(r[0] for r in rows)

    if not source_modules:
        conn.close()
        return {"affected_files": [], "affected_symbols": [], "source_modules": []}

    # Find importers: symbols whose module imports any of the changed modules
    affected_fqns: set[str] = set()
    for mod in source_modules:
        rows = conn.execute(
            "SELECT DISTINCT source_fqn FROM edges WHERE target_fqn LIKE ? AND edge_type = 'import'",
            (f"{mod}%",),
        ).fetchall()
        affected_fqns.update(r[0] for r in rows)

    # Resolve to file paths
    affected_files: set[str] = set()
    affected_symbols: list[dict] = []
    tokens_used = 0
    for fqn in sorted(affected_fqns):
        row = conn.execute(
            "SELECT name, fqn, kind, file_path, start_line, signature FROM symbols WHERE fqn = ?",
            (fqn,),
        ).fetchone()
        if not row:
            continue
        token_cost = 30
        if tokens_used + token_cost > max_tokens:
            break
        tokens_used += token_cost
        d = dict(row)
        affected_symbols.append(d)
        affected_files.add(d["file_path"])

    conn.close()
    return {
        "source_modules": source_modules,
        "affected_files": sorted(affected_files),
        "affected_symbols": affected_symbols,
        "tokens_used": tokens_used,
    }
