"""
willow-mcp MCP server — agent-neutral core tools.

Tools:
  Store (SQLite):  store_put, store_get, store_list, store_search, store_delete, store_search_all
  Knowledge (PG):  knowledge_search, knowledge_ingest
  Tasks (PG):      task_submit, task_status, task_list

Auth: SAP/1.0 — app_id required on every call. Set SAP_PGP_FINGERPRINT to pin your key.
"""

import json
import os
import sys
import uuid
from typing import Any

import mcp.server.stdio
import mcp.types as types
from mcp.server import Server

from .db import Store, get_pg

try:
    from openclaw_sap_gate import authorized as _sap_authorized
    _SAP_AVAILABLE = True
except ImportError:
    _SAP_AVAILABLE = False

_store = Store()
_server = Server("willow-mcp")
_DEFAULT_APP_ID = os.environ.get("WILLOW_APP_ID", "willow-mcp")


def _auth(app_id: str) -> tuple[bool, str]:
    """Check SAP authorization. Returns (ok, error_message)."""
    if not _SAP_AVAILABLE:
        return True, ""
    if not app_id:
        return False, "app_id is required"
    if not _sap_authorized(app_id):
        return False, f"SAP gate denied: '{app_id}' not authorized"
    return True, ""


@_server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="store_put",
            description=(
                "Write a record to a named collection. Append-only — every write gets a unique ID. "
                "Returns the record ID and an action label (work_quiet/flag/stop) based on the angular "
                "deviation rubric. High deviation (>0.6 rad) auto-flags the record for review."
            ),
            inputSchema={"type": "object", "required": ["app_id", "collection", "record"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier — must match your SAFE manifest app_id"},
                             "collection": {"type": "string", "description": "Collection path, e.g. 'knowledge/atoms', 'agents/kart', 'feedback'"},
                             "record": {"type": "object", "description": "Record data as a JSON object — any shape"},
                             "record_id": {"type": "string", "description": "Optional custom ID. Auto-generated (BASE17) if omitted."},
                             "deviation": {"type": "number", "default": 0, "description": "Angular deviation in radians: 0=routine, 0.785=significant, 1.571=major, 3.14=reversal"},
                         }},
        ),
        types.Tool(
            name="store_get",
            description="Read a single record by ID from a collection. Returns the full record object, or {error: not_found} if missing.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "record_id"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "collection": {"type": "string", "description": "Collection path the record lives in"},
                             "record_id": {"type": "string", "description": "Record ID returned by store_put or store_search"},
                         }},
        ),
        types.Tool(
            name="store_list",
            description=(
                "Return every record in a collection. Use store_search for large collections — "
                "store_list returns everything with no filtering."
            ),
            inputSchema={"type": "object", "required": ["app_id", "collection"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "collection": {"type": "string", "description": "Collection path to enumerate, e.g. 'hanuman/flags'"},
                         }},
        ),
        types.Tool(
            name="store_update",
            description="Update an existing record in-place. Every update is audit-trailed with the previous value. Use store_put to create new records.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "record_id", "record"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "collection": {"type": "string", "description": "Collection path containing the record"},
                             "record_id": {"type": "string", "description": "ID of the record to update"},
                             "record": {"type": "object", "description": "New record data — replaces the existing record entirely"},
                             "deviation": {"type": "number", "default": 0, "description": "Angular deviation in radians for this change (default 0)"},
                         }},
        ),
        types.Tool(
            name="store_search",
            description=(
                "Full-text search within a single collection. All query tokens must match (AND logic). "
                "Use store_search_all to search across every collection at once."
            ),
            inputSchema={"type": "object", "required": ["app_id", "collection", "query"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "collection": {"type": "string", "description": "Collection path to search within"},
                             "query": {"type": "string", "description": "Search terms — multiple words are ANDed together"},
                         }},
        ),
        types.Tool(
            name="store_delete",
            description=(
                "Soft-delete a record — it becomes invisible to store_get and store_search but is retained "
                "in the audit trail. Not a hard delete; the record can be recovered. "
                "To archive instead, use store_update with domain='archived'."
            ),
            inputSchema={"type": "object", "required": ["app_id", "collection", "record_id"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "collection": {"type": "string", "description": "Collection path containing the record"},
                             "record_id": {"type": "string", "description": "ID of the record to soft-delete"},
                         }},
        ),
        types.Tool(
            name="store_search_all",
            description=(
                "Search across ALL SOIL collections simultaneously. Use when you don't know which "
                "collection holds the answer. Slower than store_search — prefer store_search when the "
                "collection is known."
            ),
            inputSchema={"type": "object", "required": ["app_id", "query"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "query": {"type": "string", "description": "Search terms to match across every collection"},
                         }},
        ),
        types.Tool(
            name="knowledge_ingest",
            description=(
                "Add a knowledge atom to the Postgres knowledge base (LOAM). "
                "Writes to the knowledge table. Check for duplicates before ingesting. "
                "Requires Postgres to be available."
            ),
            inputSchema={"type": "object", "required": ["app_id", "content"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "content": {"type": "string", "description": "Atom content or file path — for file-backed atoms, store the path here"},
                             "domain": {"type": "string", "default": "general", "description": "Domain namespace: 'general', 'code', 'decision', 'reference', or a custom namespace"},
                             "source": {"type": "string", "description": "Origin identifier, e.g. session ID, file path, or URL (optional)"},
                             "tags": {"type": "array", "items": {"type": "string"}, "description": "Optional list of tag strings for filtering"},
                         }},
        ),
        types.Tool(
            name="knowledge_search",
            description=(
                "Search the Postgres knowledge base (LOAM) by content. "
                "All query tokens must match. Filter by domain to narrow results. "
                "Requires Postgres to be available."
            ),
            inputSchema={"type": "object", "required": ["app_id", "query"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "query": {"type": "string", "description": "Search terms — all tokens must appear in the content"},
                             "domain": {"type": "string", "description": "Optional domain filter to restrict results to one namespace"},
                             "limit": {"type": "integer", "default": 10, "description": "Maximum number of results to return (default 10)"},
                         }},
        ),
        types.Tool(
            name="task_submit",
            description=(
                "Submit a task to the Kart sandboxed execution queue. Kart runs the task in a bubblewrap "
                "sandbox (no network, isolated PID/filesystem). Returns a task_id for polling with task_status. "
                "Requires Postgres to be available."
            ),
            inputSchema={"type": "object", "required": ["app_id", "task"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier — also recorded as the submitting agent"},
                             "task": {"type": "string", "description": "Shell command or task description for Kart to execute"},
                             "agent": {"type": "string", "default": "kart", "description": "Target worker agent (default: 'kart')"},
                         }},
        ),
        types.Tool(
            name="task_status",
            description="Poll the status of a submitted Kart task by task_id. Returns status, result, and completion time.",
            inputSchema={"type": "object", "required": ["app_id", "task_id"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "task_id": {"type": "string", "description": "Task ID returned by task_submit"},
                         }},
        ),
        types.Tool(
            name="task_list",
            description="List pending tasks in the Kart queue. Use to inspect backlog before submitting new work.",
            inputSchema={"type": "object", "required": ["app_id"],
                         "properties": {
                             "app_id": {"type": "string", "description": "SAP/1.0 app identifier"},
                             "agent": {"type": "string", "default": "kart", "description": "Agent queue to inspect (default: 'kart')"},
                             "limit": {"type": "integer", "default": 10, "description": "Maximum number of pending tasks to return (default 10)"},
                         }},
        ),
    ]


@_server.call_tool()
async def call_tool(name: str, arguments: dict) -> list[types.TextContent]:
    app_id = arguments.get("app_id", _DEFAULT_APP_ID)
    ok, err = _auth(app_id)
    if not ok:
        return [types.TextContent(type="text", text=json.dumps({"error": err}))]

    try:
        result = await _dispatch(name, arguments)
    except Exception as e:
        result = {"error": str(e)}

    return [types.TextContent(type="text", text=json.dumps(result))]


async def _dispatch(name: str, args: dict) -> Any:
    # ── Store ──────────────────────────────────────────────────────────
    if name == "store_put":
        rid, action = _store.put(
            args["collection"],
            args["record"],
            record_id=args.get("record_id"),
            deviation=args.get("deviation", 0.0),
        )
        return {"id": rid, "action": action}

    if name == "store_get":
        item = _store.get(args["collection"], args["record_id"])
        return item or {"error": "not_found"}

    if name == "store_list":
        return _store.all(args["collection"])

    if name == "store_update":
        rid = _store.update(
            args["collection"],
            args["record_id"],
            args["record"],
            deviation=args.get("deviation", 0.0),
        )
        return {"id": rid} if rid else {"error": "not_found"}

    if name == "store_search":
        return _store.search(args["collection"], args["query"])

    if name == "store_delete":
        deleted = _store.delete(args["collection"], args["record_id"])
        return {"deleted": deleted}

    if name == "store_search_all":
        return _store.search_all(args["query"])

    # ── Knowledge ──────────────────────────────────────────────────────
    if name == "knowledge_ingest":
        pg = get_pg()
        if not pg:
            return {"error": "postgres_unavailable"}
        cur = pg.cursor()
        kid = str(uuid.uuid4())[:8].upper()
        cur.execute(
            "INSERT INTO knowledge (id, content, domain, source, tags) "
            "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
            (kid, args["content"], args.get("domain", "general"),
             args.get("source", ""), json.dumps(args.get("tags", [])))
        )
        cur.close()
        return {"id": kid}

    if name == "knowledge_search":
        pg = get_pg()
        if not pg:
            return {"error": "postgres_unavailable"}
        cur = pg.cursor()
        tokens = args["query"].split()
        conditions = " AND ".join(["content ILIKE %s"] * len(tokens))
        params = [f"%{t}%" for t in tokens]
        sql = f"SELECT id, content, domain, source FROM knowledge WHERE {conditions}"
        if args.get("domain"):
            sql += " AND domain = %s"
            params.append(args["domain"])
        sql += " LIMIT %s"
        params.append(args.get("limit", 10))
        cur.execute(sql, params)
        rows = cur.fetchall()
        cur.close()
        return {"results": [{"id": r[0], "content": r[1], "domain": r[2], "source": r[3]}
                             for r in rows]}

    # ── Task Queue ─────────────────────────────────────────────────────
    if name == "task_submit":
        pg = get_pg()
        if not pg:
            return {"error": "postgres_unavailable"}
        task_id = "".join(__import__("random").choices(
            "ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=8))
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO kart_task_queue (task_id, submitted_by, agent, task) "
            "VALUES (%s, %s, %s, %s)",
            (task_id, args.get("app_id", "willow-mcp"),
             args.get("agent", "kart"), args["task"])
        )
        cur.close()
        return {"task_id": task_id, "status": "pending"}

    if name == "task_status":
        pg = get_pg()
        if not pg:
            return {"error": "postgres_unavailable"}
        cur = pg.cursor()
        cur.execute(
            "SELECT task_id, status, result, steps, created_at, completed_at "
            "FROM kart_task_queue WHERE task_id = %s",
            (args["task_id"],)
        )
        row = cur.fetchone()
        cur.close()
        if not row:
            return {"error": "not_found"}
        return {"task_id": row[0], "status": row[1], "result": row[2],
                "steps": row[3], "created_at": str(row[4]), "completed_at": str(row[5])}

    if name == "task_list":
        pg = get_pg()
        if not pg:
            return {"error": "postgres_unavailable"}
        cur = pg.cursor()
        cur.execute(
            "SELECT task_id, task, submitted_by, created_at FROM kart_task_queue "
            "WHERE status = 'pending' AND agent = %s ORDER BY created_at LIMIT %s",
            (args.get("agent", "kart"), args.get("limit", 10))
        )
        rows = cur.fetchall()
        cur.close()
        return {"pending": [{"task_id": r[0], "task": r[1][:80],
                              "submitted_by": r[2], "created_at": str(r[3])}
                             for r in rows]}

    return {"error": f"unknown_tool: {name}"}


def main():
    import asyncio
    asyncio.run(_run())


async def _run():
    async with mcp.server.stdio.stdio_server() as (r, w):
        await _server.run(r, w, _server.create_initialization_options())


if __name__ == "__main__":
    main()
