"""
willow-mcp MCP server — agent-neutral core tools.

Modes:
  stdio (default):  python3 -m willow_mcp
  serve (HTTP):     python3 -m willow_mcp --serve [--port 8765] [--host 127.0.0.1]

Tools:
  Store (SQLite):  store_put, store_get, store_list, store_update, store_search,
                   store_delete, store_search_all
  Knowledge (PG):  knowledge_ingest, knowledge_search,
                   kb_at, kb_promote, kb_journal, kb_startup_continuity
  Tasks (PG):      task_submit, task_status, task_list
  Agent (PG):      agent_route, agent_dispatch_result
  Fleet (PG):      fleet_status, fleet_health

Auth (stdio): manifest-based per-tool ACL — app_id required on every call.
Auth (serve): OAuth 2.0 PKCE (Google / Apple) + per-tool ACL gate.
Fail-closed: no manifest = all calls denied.

Security (Phase 4): every tool call runs sanitize -> rate-check -> gate ->
dispatch -> receipt, via the _guarded() decorator. See _sanitize, _check_rate,
and receipts.ReceiptLog.
"""
# b17: WLWMCP  ΔΣ=42

import inspect
import json
import math
import os
import re
import sys
import threading
import time
import uuid
from functools import wraps
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP

from .db import Store, get_pg
from .gate import permitted
from .receipts import ReceiptLog

_store = Store()
_receipt_log = ReceiptLog()

_PORT = int(os.getenv("WILLOW_MCP_PORT", "8765"))
_HOST = os.getenv("WILLOW_MCP_HOST", "127.0.0.1")
_DEFAULT_APP_ID = os.environ.get("WILLOW_APP_ID", "")

_SERVE_MODE = "--serve" in sys.argv

_BASE_URL_ENV = (os.getenv("WILLOW_MCP_URL") or "").strip().rstrip("/")
_BASE_URL = _BASE_URL_ENV if _BASE_URL_ENV else f"http://{_HOST}:{_PORT}"

_common_kwargs: dict[str, Any] = dict(
    instructions=(
        "Willow sovereign agent platform. "
        "Store, retrieve, and search records; ingest and query the knowledge base; "
        "submit and monitor sandboxed Kart tasks. "
        "Pass app_id on every call — matches your manifest in $WILLOW_HOME/mcp_apps/<app_id>/manifest.json."
    ),
    host=_HOST,
    port=_PORT,
)

if _SERVE_MODE:
    from .oauth import WillowOAuthProvider
    from .vault import default_vault
    from mcp.server.auth.settings import AuthSettings, ClientRegistrationOptions
    import pathlib

    _vault = default_vault()
    _willow_home = pathlib.Path(os.environ.get("WILLOW_HOME", pathlib.Path.home() / ".willow"))
    _auth_provider = WillowOAuthProvider(
        token_path=_willow_home / "mcp_token.json",
        base_url=_BASE_URL,
        vault=_vault,
    )
    mcp = FastMCP(
        "willow-mcp",
        **_common_kwargs,
        auth_server_provider=_auth_provider,
        auth=AuthSettings(
            issuer_url=_BASE_URL + "/",
            resource_server_url=_BASE_URL + "/",
            client_registration_options=ClientRegistrationOptions(
                enabled=True,
                valid_scopes=["willow"],
                default_scopes=["willow"],
            ),
            required_scopes=["willow"],
        ),
    )
    _auth_provider.register_routes(mcp)
else:
    mcp = FastMCP("willow-mcp", **_common_kwargs)


# ── Gate helper ────────────────────────────────────────────────────────────────

def _gate(app_id: str, tool_name: str) -> dict | None:
    """Return an error dict if the call is denied, else None."""
    effective = app_id or _DEFAULT_APP_ID
    if not permitted(effective, tool_name):
        return {
            "error": (
                f"gate denied: '{effective}' not permitted for '{tool_name}'. "
                f"Ensure a manifest exists at $WILLOW_HOME/mcp_apps/{effective}/manifest.json "
                f"and lists this tool or a group that includes it."
            )
        }
    return None


# ── Sanitizer (Phase 4a) ─────────────────────────────────────────────────────

_MAX_BLOB_BYTES = 512 * 1024   # record / context dicts
_MAX_STR_BYTES = 64 * 1024     # content / task / query strings
_MAX_TAGS = 32
_MAX_TAG_LEN = 128
_PATH_TRAVERSAL_RE = re.compile(r"\.\.|[/\\]")


def _sanitize(kwargs: dict) -> tuple[dict, Optional[str]]:
    """Clean known-risky fields by name, regardless of which tool they belong to.

    Returns (cleaned_kwargs, None) on success, or (kwargs, error_message) if a
    field fails validation outright (caller denies the call — no partial writes).
    """
    for key in ("record", "context"):
        val = kwargs.get(key)
        if isinstance(val, dict):
            size = len(json.dumps(val))
            if size > _MAX_BLOB_BYTES:
                return kwargs, f"'{key}' exceeds 512KB limit ({size} bytes)"

    for key in ("content", "task", "query"):
        val = kwargs.get(key)
        if isinstance(val, str):
            cleaned = val.replace("\x00", "")
            encoded = cleaned.encode("utf-8")
            if len(encoded) > _MAX_STR_BYTES:
                cleaned = encoded[:_MAX_STR_BYTES].decode("utf-8", errors="ignore")
            kwargs[key] = cleaned

    collection = kwargs.get("collection")
    if isinstance(collection, str) and _PATH_TRAVERSAL_RE.search(collection):
        return kwargs, "'collection' contains illegal path characters"

    tags = kwargs.get("tags")
    if isinstance(tags, list):
        if len(tags) > _MAX_TAGS:
            return kwargs, f"'tags' exceeds max {_MAX_TAGS} items"
        for t in tags:
            if isinstance(t, str) and len(t) > _MAX_TAG_LEN:
                return kwargs, f"tag exceeds max {_MAX_TAG_LEN} chars"

    return kwargs, None


# ── Rate limiter (Phase 4b) ──────────────────────────────────────────────────

class _Bucket:
    __slots__ = ("tokens", "last_refill")

    def __init__(self, tokens: float, last_refill: float):
        self.tokens = tokens
        self.last_refill = last_refill


_buckets: dict[str, _Bucket] = {}
_buckets_lock = threading.Lock()
_RATE = 60.0    # tokens per minute
_BURST = 10.0   # bucket capacity


def _check_rate(app_id: str) -> tuple[bool, int]:
    """Token bucket, in-process, no external dependency.

    Single-operator assumption matches the rest of the package — a
    multi-process deploy can swap this for a pluggable backend later.
    Returns (allowed, retry_after_seconds).
    """
    now = time.monotonic()
    with _buckets_lock:
        bucket = _buckets.get(app_id)
        if bucket is None:
            bucket = _Bucket(tokens=_BURST, last_refill=now)
            _buckets[app_id] = bucket
        elapsed = now - bucket.last_refill
        bucket.tokens = min(_BURST, bucket.tokens + elapsed * (_RATE / 60.0))
        bucket.last_refill = now
        if bucket.tokens < 1.0:
            deficit = 1.0 - bucket.tokens
            retry_after = max(1, math.ceil(deficit / (_RATE / 60.0)))
            return False, retry_after
        bucket.tokens -= 1.0
        return True, 0


# ── Guarded dispatch (Phase 4a+4b+4c combined) ───────────────────────────────

def _guarded(tool_name: str, *, list_error: bool = False):
    """Central pipeline: sanitize -> rate check -> gate -> dispatch -> receipt.

    list_error=True for tools whose declared return type is list (store_list,
    store_search, store_search_all) so a denial comes back list-wrapped,
    matching that tool's own success-path shape.
    """
    def decorator(fn):
        sig = inspect.signature(fn)

        @wraps(fn)
        def wrapper(*args, **kwargs):
            bound = sig.bind(*args, **kwargs)
            bound.apply_defaults()
            call_kwargs = dict(bound.arguments)
            app_id = call_kwargs.get("app_id", "") or _DEFAULT_APP_ID

            def _shape(err: dict):
                return [err] if list_error else err

            cleaned, problem = _sanitize(call_kwargs)
            if problem:
                _receipt_log.record(app_id, tool_name, "error", f"sanitize: {problem}")
                return _shape({"error": f"sanitize: {problem}"})
            call_kwargs = cleaned

            allowed, retry_after = _check_rate(app_id)
            if not allowed:
                _receipt_log.record(app_id, tool_name, "rate_limited", f"retry_after={retry_after}")
                return _shape({"error": "rate_limited", "retry_after": retry_after})

            gate_err = _gate(app_id, tool_name)
            if gate_err:
                _receipt_log.record(app_id, tool_name, "denied", gate_err.get("error"))
                return _shape(gate_err)

            try:
                result = fn(**call_kwargs)
            except Exception as e:
                _receipt_log.record(app_id, tool_name, "error", f"{type(e).__name__}: {e}")
                raise

            probe = (result[0] if (isinstance(result, list) and result
                                    and isinstance(result[0], dict)) else result)
            if isinstance(probe, dict) and "error" in probe:
                _receipt_log.record(app_id, tool_name, "error", str(probe["error"]))
            else:
                _receipt_log.record(app_id, tool_name, "ok", None)

            return result

        return wrapper
    return decorator


# ── Store tools ────────────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("store_put")
def store_put(
    app_id: str,
    collection: str,
    record: dict,
    record_id: Optional[str] = None,
    deviation: float = 0.0,
) -> dict:
    """Write a record to a named collection. Returns {id, action}. High deviation (>0.6 rad) auto-flags."""
    rid, action = _store.put(collection, record, record_id=record_id, deviation=deviation)
    return {"id": rid, "action": action}


@mcp.tool()
@_guarded("store_get")
def store_get(app_id: str, collection: str, record_id: str) -> dict:
    """Read a single record by ID. Returns the record or {error: not_found}."""
    item = _store.get(collection, record_id)
    return item or {"error": "not_found"}


@mcp.tool()
@_guarded("store_list", list_error=True)
def store_list(app_id: str, collection: str) -> list:
    """Return every record in a collection (unfiltered). Prefer store_search for large collections."""
    return _store.all(collection)


@mcp.tool()
@_guarded("store_update")
def store_update(
    app_id: str,
    collection: str,
    record_id: str,
    record: dict,
    deviation: float = 0.0,
) -> dict:
    """Update an existing record in-place with audit trail. Use store_put to create."""
    rid = _store.update(collection, record_id, record, deviation=deviation)
    return {"id": rid} if rid else {"error": "not_found"}


@mcp.tool()
@_guarded("store_search", list_error=True)
def store_search(app_id: str, collection: str, query: str) -> list:
    """Full-text search within a single collection (AND logic across tokens)."""
    return _store.search(collection, query)


@mcp.tool()
@_guarded("store_delete")
def store_delete(app_id: str, collection: str, record_id: str) -> dict:
    """Soft-delete a record — invisible to get/search but retained in audit trail."""
    deleted = _store.delete(collection, record_id)
    return {"deleted": deleted}


@mcp.tool()
@_guarded("store_search_all", list_error=True)
def store_search_all(app_id: str, query: str) -> list:
    """Search across ALL SOIL collections. Use when the collection is unknown."""
    return _store.search_all(query)


# ── Knowledge tools ────────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("knowledge_ingest")
def knowledge_ingest(
    app_id: str,
    content: str,
    domain: str = "general",
    source: str = "",
    tags: Optional[list] = None,
) -> dict:
    """Add a knowledge atom to the Postgres knowledge base. Check for duplicates first."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    kid = str(uuid.uuid4())[:8].upper()
    cur = pg.cursor()
    cur.execute(
        "INSERT INTO knowledge (id, content, domain, source, tags) "
        "VALUES (%s, %s, %s, %s, %s) ON CONFLICT DO NOTHING",
        (kid, content, domain, source, json.dumps(tags or []))
    )
    cur.close()
    return {"id": kid}


@mcp.tool()
@_guarded("knowledge_search")
def knowledge_search(
    app_id: str,
    query: str,
    domain: Optional[str] = None,
    limit: int = 10,
) -> dict:
    """Search the Postgres knowledge base by content (AND logic). Filter by domain to narrow results."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    tokens = query.split()
    conditions = " AND ".join(["content ILIKE %s"] * len(tokens))
    params: list = [f"%{t}%" for t in tokens]
    sql = f"SELECT id, content, domain, source FROM knowledge WHERE {conditions}"
    if domain:
        sql += " AND domain = %s"
        params.append(domain)
    sql += " LIMIT %s"
    params.append(limit)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return {"results": [{"id": r[0], "content": r[1], "domain": r[2], "source": r[3]}
                         for r in rows]}


# ── Task queue tools ───────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("task_submit")
def task_submit(app_id: str, task: str, agent: str = "kart") -> dict:
    """Submit a task to the Kart sandboxed execution queue. Returns task_id for polling."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    import random
    task_id = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=8))
    cur = pg.cursor()
    cur.execute(
        "INSERT INTO kart_task_queue (task_id, submitted_by, agent, task) "
        "VALUES (%s, %s, %s, %s)",
        (task_id, app_id or "willow-mcp", agent, task)
    )
    cur.close()
    return {"task_id": task_id, "status": "pending"}


@mcp.tool()
@_guarded("task_status")
def task_status(app_id: str, task_id: str) -> dict:
    """Poll the status of a submitted Kart task. Returns status, result, and completion time."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    cur.execute(
        "SELECT task_id, status, result, steps, created_at, completed_at "
        "FROM kart_task_queue WHERE task_id = %s",
        (task_id,)
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"error": "not_found"}
    return {"task_id": row[0], "status": row[1], "result": row[2],
            "steps": row[3], "created_at": str(row[4]), "completed_at": str(row[5])}


@mcp.tool()
@_guarded("task_list")
def task_list(app_id: str, agent: str = "kart", limit: int = 10) -> dict:
    """List pending tasks in the Kart queue."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    cur.execute(
        "SELECT task_id, task, submitted_by, created_at FROM kart_task_queue "
        "WHERE status = 'pending' AND agent = %s ORDER BY created_at LIMIT %s",
        (agent, limit)
    )
    rows = cur.fetchall()
    cur.close()
    return {"pending": [{"task_id": r[0], "task": r[1][:80],
                          "submitted_by": r[2], "created_at": str(r[3])}
                         for r in rows]}


# ── Knowledge extension tools ──────────────────────────────────────────────────

@mcp.tool()
@_guarded("kb_at")
def kb_at(app_id: str, atom_id: str) -> dict:
    """Fetch a single knowledge atom by ID. Returns the full atom or {error: not_found}."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    cur.execute(
        "SELECT id, content, domain, source, tags FROM knowledge WHERE id = %s",
        (atom_id,)
    )
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"error": "not_found"}
    return {"id": row[0], "content": row[1], "domain": row[2],
            "source": row[3], "tags": json.loads(row[4] or "[]")}


@mcp.tool()
@_guarded("kb_promote")
def kb_promote(app_id: str, atom_id: str, domain: str) -> dict:
    """Change the domain of an existing knowledge atom."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    cur.execute(
        "UPDATE knowledge SET domain = %s WHERE id = %s",
        (domain, atom_id)
    )
    updated = cur.rowcount
    cur.close()
    return {"id": atom_id, "domain": domain} if updated else {"error": "not_found"}


@mcp.tool()
@_guarded("kb_journal")
def kb_journal(
    app_id: str,
    content: str,
    source: str = "",
    tags: Optional[list] = None,
) -> dict:
    """Add a journal entry to the knowledge base (domain='journal')."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    kid = str(uuid.uuid4())[:8].upper()
    all_tags = list(set(["journal"] + (tags or [])))
    cur = pg.cursor()
    cur.execute(
        "INSERT INTO knowledge (id, content, domain, source, tags) "
        "VALUES (%s, %s, 'journal', %s, %s) ON CONFLICT DO NOTHING",
        (kid, content, source, json.dumps(all_tags))
    )
    cur.close()
    return {"id": kid, "domain": "journal"}


@mcp.tool()
@_guarded("kb_startup_continuity")
def kb_startup_continuity(app_id: str, limit: int = 20) -> dict:
    """Fetch knowledge atoms tagged or domained for startup continuity."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    cur = pg.cursor()
    cur.execute(
        "SELECT id, content, domain, source FROM knowledge "
        "WHERE domain = 'continuity' OR tags LIKE %s "
        "ORDER BY id DESC LIMIT %s",
        ('%"continuity"%', limit)
    )
    rows = cur.fetchall()
    cur.close()
    return {"atoms": [{"id": r[0], "content": r[1], "domain": r[2], "source": r[3]}
                       for r in rows]}


# ── Agent dispatch tools ───────────────────────────────────────────────────────

@mcp.tool()
@_guarded("agent_route")
def agent_route(
    app_id: str,
    task: str,
    target_agent: str,
    context: Optional[dict] = None,
) -> dict:
    """Route a task to a target agent. Records in routing_decisions and returns a routing_id."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    import hashlib
    routing_id = str(uuid.uuid4())[:8].upper()
    prompt_hash = hashlib.sha256(task.encode()).hexdigest()[:16]
    decision = {"task": task, "target": target_agent, "context": context or {}}
    try:
        cur = pg.cursor()
        cur.execute(
            "INSERT INTO routing_decisions "
            "(id, prompt_hash, session_id, rule_id, confidence, decision, kind) "
            "VALUES (%s, %s, %s, %s, %s, %s, 'agent_route')",
            (routing_id, prompt_hash, app_id, target_agent, 1.0, json.dumps(decision))
        )
        cur.close()
    except Exception as e:
        return {"error": f"routing_unavailable: {e}"}
    return {"routing_id": routing_id, "target": target_agent, "status": "routed"}


@mcp.tool()
@_guarded("agent_dispatch_result")
def agent_dispatch_result(
    app_id: str,
    routing_id: str,
    result: str,
    status: str = "done",
) -> dict:
    """Record the result of a dispatched agent task."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    try:
        cur = pg.cursor()
        cur.execute(
            "UPDATE routing_decisions "
            "SET decision = decision || %s::jsonb "
            "WHERE id = %s",
            (json.dumps({"result": result, "dispatch_status": status}), routing_id)
        )
        updated = cur.rowcount
        cur.close()
    except Exception as e:
        return {"error": f"routing_unavailable: {e}"}
    return {"routing_id": routing_id, "status": status} if updated else {"error": "not_found"}


# ── Fleet read tools ───────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("fleet_status")
def fleet_status(app_id: str) -> dict:
    """List agents registered in the fleet (public.agents table)."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT id, name, role, trust, created_at FROM agents ORDER BY name"
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        return {"error": f"fleet_unavailable: {e}"}
    return {"agents": [{"id": r[0], "name": r[1], "role": r[2],
                         "trust": r[3], "since": str(r[4])} for r in rows]}


@mcp.tool()
@_guarded("fleet_health")
def fleet_health(app_id: str) -> dict:
    """Fleet health — task queue counts by status across all agents."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    try:
        cur = pg.cursor()
        cur.execute(
            "SELECT status, COUNT(*) FROM kart_task_queue GROUP BY status"
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        return {"error": f"fleet_unavailable: {e}"}
    counts = {r[0]: r[1] for r in rows}
    return {
        "pending":   counts.get("pending", 0),
        "running":   counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed":    counts.get("failed", 0),
        "total":     sum(counts.values()),
    }


# ── Entry points ───────────────────────────────────────────────────────────────

def main():
    import argparse
    parser = argparse.ArgumentParser(prog="willow-mcp")
    parser.add_argument("--serve", action="store_true", help="Run as HTTP server with OAuth")
    parser.add_argument("--port", type=int, default=_PORT)
    parser.add_argument("--host", default=_HOST)
    args, _ = parser.parse_known_args()

    if args.serve or _SERVE_MODE:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
