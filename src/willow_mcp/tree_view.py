"""willow_mcp/tree_view.py — one call, the whole tree.

`docs/design/*.html` reads this codebase's tool surface as a tree: trunk =
overall health, sap = the task queue in motion, canopy = the agent fleet,
roots = the persistent SOIL store, rings = confirmed schema mappings,
leaves = knowledge atoms, litter = the receipt log, and (added alongside
`willow-mcp gates`) stomata = the authorization gates governing what an app
may exchange with the world outside. Those mockups fabricate all eight;
`build_tree()` is the integration seam that makes them real — one function a
real dashboard can call (directly, or via the `willow-mcp tree` CLI) to get
every part in the same shape, instead of assembling eight separate tool
calls itself.

**This reuses existing tools, it does not re-implement them.** `sap` and
`canopy` call straight into `server.fleet_health`/`server.fleet_status` — the
same `@_guarded` functions an MCP client would reach — so gating, rate
limiting, and receipt logging all still apply exactly as they do over MCP.
`roots`, `rings`, `litter`, and `stomata` read local SQLite/filesystem state
directly (`db.Store`, on-disk schema-map artifacts, `ReceiptLog`,
`gates_panel`) the same way `willow-mcp gates`/`net-status` already do,
so they work even with no Postgres configured.

**Postgres-backed parts degrade, they don't crash.** `sap`, `canopy`, and
`leaves` all return `{"error": "postgres_unavailable"}` (the same shape
`fleet_health`/`fleet_status`/`kb_startup_continuity` already return) when no
database is reachable — a dashboard built against this should treat that key
as "this part of the tree has nothing to show yet," not as a fatal response.

`leaves` is deliberately built from `kb_startup_continuity`, not a literal
"most recent atoms" query — that's the closest existing read primitive.
Swap it for a dedicated recency-ordered fetch if a real dashboard needs
exactly "last N ingested," rather than continuity-tagged atoms.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Optional


def _rings(app_id: str) -> dict:
    """Confirmed/unconfirmed schema mappings, read straight off the
    `schema_maps/*.json` artifacts `schema_profile.py` already writes — no
    live Postgres connection needed, same as `gates_panel`'s file reads.
    Reflects the last-resolved state, not a fresh introspection: schema
    drift is only caught the next time something calls `schema_profile.resolve`
    against a live connection.
    """
    from . import paths

    root = paths.mcp_apps_root() / app_id / "schema_maps"
    tables = []
    if root.is_dir():
        for f in sorted(root.glob("*.json")):
            try:
                record = json.loads(f.read_text(encoding="utf-8"))
            except Exception:
                continue  # a torn or hand-mangled file is not a mapping
            tables.append({
                "table": record.get("table", f.stem),
                "confirmed": bool(record.get("confirmed")),
                "schema_drift": bool(record.get("schema_drift")),
                "discovered_at": record.get("discovered_at"),
            })
    confirmed = sum(1 for t in tables if t["confirmed"])
    return {"tables": tables, "confirmed": confirmed, "total": len(tables)}


def _roots(app_id: str) -> dict:
    """Every SOIL collection this app can see (its `store_scope`, or every
    collection if it has none) — no query, just what exists."""
    from . import gate
    from .db import Store

    store = Store()
    scope = gate.store_scope(app_id)
    collections = store.list_collections(scope)
    return {"collections": collections, "count": len(collections),
            "scoped": scope is not None}


def build_tree(app_id: str) -> dict:
    """Every tree part, one call. See module docstring for the shape and
    which parts require Postgres."""
    from . import gates_panel
    from . import server  # deferred: server.py imports heavily (mcp, psycopg2)
                           # and this must stay import-safe for callers that
                           # only want the local (non-guarded) parts.

    sap = server.fleet_health(app_id)
    canopy = server.fleet_status(app_id)
    roots = _roots(app_id)
    rings = _rings(app_id)
    leaves = server.kb_startup_continuity(app_id, limit=5)
    litter = server.receipts_tail(app_id, limit=10)
    stomata = [row.__dict__ for row in gates_panel.collect(app_id)]
    diag = server.diagnostic_summary(app_id)

    trunk = {
        "verdict": diag.get("verdict"),
        "problems": diag.get("problems", []),
        "tasks_total": sap.get("total") if "error" not in sap else None,
        "tasks_failed": sap.get("failed") if "error" not in sap else None,
        "tasks_pending": sap.get("pending") if "error" not in sap else None,
        "agents": len(canopy.get("agents", [])) if "error" not in canopy else None,
        "tables_ringed": rings["confirmed"],
        "tables_total": rings["total"],
    }

    return {
        "app_id": app_id,
        "trunk": trunk,
        "sap": sap,
        "canopy": canopy,
        "roots": roots,
        "rings": rings,
        "leaves": leaves,
        "litter": litter,
        "stomata": stomata,
    }


def render_summary(tree: dict) -> str:
    """A short human-readable digest — not a replacement for a real
    dashboard, just enough to eyeball `willow-mcp tree` output in a
    terminal."""
    t = tree["trunk"]
    lines = [
        f"willow-mcp tree — app_id={tree['app_id']!r}",
        f"  trunk    verdict={t['verdict']}"
        f" tasks={t['tasks_total']} failed={t['tasks_failed']} pending={t['tasks_pending']}"
        f" agents={t['agents']} rings={t['tables_ringed']}/{t['tables_total']}",
    ]
    sap = tree["sap"]
    if "error" in sap:
        sap_line = sap["error"]
    else:
        sap_line = ", ".join(f"{k}={v}" for k, v in sap.items() if k != "workers")
    lines.append(f"  sap      {sap_line}")

    canopy = tree["canopy"]
    if "error" in canopy:
        canopy_line = canopy["error"]
    else:
        canopy_line = f"{len(canopy.get('agents', []))} agents"
    lines.append(f"  canopy   {canopy_line}")

    lines.append(f"  roots    {tree['roots']['count']} collections"
                 f" ({'scoped' if tree['roots']['scoped'] else 'unscoped'})")
    lines.append(f"  rings    {tree['rings']['confirmed']}/{tree['rings']['total']} confirmed")

    leaves = tree["leaves"]
    if "error" in leaves:
        leaves_line = leaves["error"]
    else:
        atoms = leaves.get("atoms", leaves.get("results", []))
        leaves_line = f"{len(atoms)} atoms"
    lines.append(f"  leaves   {leaves_line}")

    lines.append(f"  litter   {len(tree['litter'].get('receipts', []))} recent receipts")
    on = sum(1 for row in tree["stomata"] if row["state"] == "on")
    lines.append(f"  stomata  {on}/{len(tree['stomata'])} open — see `willow-mcp gates` for detail")
    return "\n".join(lines)
