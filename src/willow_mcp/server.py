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
            description="Write a value to the local SQLite store.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "content"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "collection": {"type": "string"},
                             "content": {"type": "string"},
                             "domain": {"type": "string", "default": "default"},
                             "id": {"type": "string"},
                         }},
        ),
        types.Tool(
            name="store_get",
            description="Read a value from the local SQLite store by ID.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "id"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "collection": {"type": "string"},
                             "id": {"type": "string"},
                         }},
        ),
        types.Tool(
            name="store_list",
            description="List atoms in a collection.",
            inputSchema={"type": "object", "required": ["app_id", "collection"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "collection": {"type": "string"},
                             "domain": {"type": "string"},
                             "limit": {"type": "integer", "default": 20},
                         }},
        ),
        types.Tool(
            name="store_search",
            description="Full-text search within a collection.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "query"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "collection": {"type": "string"},
                             "query": {"type": "string"},
                             "limit": {"type": "integer", "default": 10},
                         }},
        ),
        types.Tool(
            name="store_delete",
            description="Delete an atom from the store.",
            inputSchema={"type": "object", "required": ["app_id", "collection", "id"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "collection": {"type": "string"},
                             "id": {"type": "string"},
                         }},
        ),
        types.Tool(
            name="store_search_all",
            description="Search across all collections.",
            inputSchema={"type": "object", "required": ["app_id", "query"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "query": {"type": "string"},
                             "limit": {"type": "integer", "default": 10},
                         }},
        ),
        types.Tool(
            name="knowledge_ingest",
            description="Add a knowledge atom to the Postgres knowledge base.",
            inputSchema={"type": "object", "required": ["app_id", "content"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "content": {"type": "string"},
                             "domain": {"type": "string", "default": "general"},
                             "source": {"type": "string"},
                             "tags": {"type": "array", "items": {"type": "string"}},
                         }},
        ),
        types.Tool(
            name="knowledge_search",
            description="Search the Postgres knowledge base.",
            inputSchema={"type": "object", "required": ["app_id", "query"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "query": {"type": "string"},
                             "domain": {"type": "string"},
                             "limit": {"type": "integer", "default": 10},
                         }},
        ),
        types.Tool(
            name="task_submit",
            description="Submit a task to the Kart execution queue.",
            inputSchema={"type": "object", "required": ["app_id", "task"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "task": {"type": "string", "description": "Task text for Kart to execute"},
                             "agent": {"type": "string", "default": "kart"},
                         }},
        ),
        types.Tool(
            name="task_status",
            description="Check status of a submitted task.",
            inputSchema={"type": "object", "required": ["app_id", "task_id"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "task_id": {"type": "string"},
                         }},
        ),
        types.Tool(
            name="task_list",
            description="List pending tasks in the queue.",
            inputSchema={"type": "object", "required": ["app_id"],
                         "properties": {
                             "app_id": {"type": "string"},
                             "agent": {"type": "string", "default": "kart"},
                             "limit": {"type": "integer", "default": 10},
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
        atom_id = _store.put(
            collection=args["collection"],
            content=args["content"],
            domain=args.get("domain", "default"),
            atom_id=args.get("id"),
        )
        return {"id": atom_id, "collection": args["collection"]}

    if name == "store_get":
        item = _store.get(args["collection"], args["id"])
        return item or {"error": "not_found"}

    if name == "store_list":
        return {"items": _store.list_atoms(
            args["collection"],
            domain=args.get("domain"),
            limit=args.get("limit", 20),
        )}

    if name == "store_search":
        return {"results": _store.search(
            args["collection"], args["query"], limit=args.get("limit", 10)
        )}

    if name == "store_delete":
        deleted = _store.delete(args["collection"], args["id"])
        return {"deleted": deleted}

    if name == "store_search_all":
        return {"results": _store.search_all(args["query"], limit=args.get("limit", 10))}

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
        query = f"%{args['query']}%"
        sql = "SELECT id, content, domain, source FROM knowledge WHERE content ILIKE %s"
        params = [query]
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
