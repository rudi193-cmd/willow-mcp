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
from psycopg2.extras import Json

from .db import Store, get_pg
from .gate import permitted
from .identity_binding import resolve_app_id
from .receipts import ReceiptLog
from . import schema_profile as sp

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

def _resolve_serve_identity() -> tuple[Optional[str], Optional[dict]]:
    """Resolve the caller's bound app_id from the authenticated OAuth session.

    Serve-mode identity binding (L-AUTH-02): a Google/Apple sign-in alone
    grants no standing. This reads the session's verified (issuer, subject)
    via the MCP SDK's contextvar-based get_access_token() — never from a
    tool-call argument — and only returns an app_id if a human has separately
    confirmed a binding for that identity (identity_binding.confirm_binding,
    CLI-only). Returns (app_id, None) on success, (None, error_dict) on any
    failure — fail closed at every step, matching an unmanifested app_id's
    behavior in stdio mode.
    """
    from mcp.server.auth.middleware.auth_context import get_access_token

    token = get_access_token()
    if token is None:
        return None, {"error": "gate denied: no authenticated session (serve mode requires OAuth sign-in)"}

    issuer = (token.claims or {}).get("iss")
    subject = token.subject
    if not issuer or not subject:
        return None, {"error": "gate denied: authenticated session carries no bound identity"}

    bound_app_id = resolve_app_id(issuer, subject)
    if not bound_app_id:
        return None, {
            "error": (
                f"gate denied: identity ({issuer}, {subject}) is signed in but not yet bound to an "
                "app_id — ask the operator to run `willow-mcp confirm-binding` for this identity"
            )
        }
    return bound_app_id, None


def _gate(app_id: str, tool_name: str) -> tuple[Optional[str], Optional[dict]]:
    """Resolve the effective app_id and check permission.

    Returns (effective_app_id, None) on success, (None, error_dict) on denial.

    Serve mode (HTTP + OAuth): the effective app_id comes ONLY from the
    authenticated session's confirmed identity binding — the tool call's own
    app_id argument is never trusted for authorization purposes here (that
    was L-AUTH-02: previously any signed-in caller could self-declare any
    app_id and get whatever that manifest permitted).

    Stdio mode (default): unchanged — app_id comes from the tool call, same
    single-operator trust model as before.
    """
    if _SERVE_MODE:
        effective, err = _resolve_serve_identity()
        if err:
            return None, err
    else:
        effective = app_id or _DEFAULT_APP_ID

    if not permitted(effective, tool_name):
        return None, {
            "error": (
                f"gate denied: '{effective}' not permitted for '{tool_name}'. "
                f"Ensure a manifest exists at $WILLOW_HOME/mcp_apps/{effective}/manifest.json "
                f"and lists this tool or a group that includes it."
            )
        }
    return effective, None


# ── Schema-adapted knowledge reads (docs/design/schema-adaptation.md §9 step 2) ─

# Canonical fields the `knowledge` read tools speak in — matches the §3.2
# example exactly. Not every host `knowledge` table will have all of these;
# unmapped ones are simply omitted from results (§3.3), never crash a read.
_KNOWLEDGE_FIELDS = ["id", "content", "domain", "source", "tags"]

# Canonical fields the `tasks` tools speak in (§9 step 5). The real production
# table is named `tasks`, not `kart_task_queue` — confirmed via live
# information_schema introspection 2026-07-08. It has no `steps` or
# `completed_at` column; those stay unmapped (null on read) rather than
# guessing at a substitute like `updated_at`, which fires on any update, not
# just completion.
_TASK_FIELDS = ["task_id", "task", "submitted_by", "agent", "status", "result",
                 "steps", "created_at", "completed_at"]

# Registry of tables schema_confirm_mapping knows how to confirm, and the
# canonical fields each one speaks in. Extend this when a new table gets a
# schema-adapted write path.
_CONFIRMABLE_TABLES: dict[str, list[str]] = {
    "knowledge": _KNOWLEDGE_FIELDS,
    "tasks": _TASK_FIELDS,
}


def _build_select(fields_wanted: list[str], mapping_fields: dict) -> tuple[str, list[str], list[str]]:
    """From a resolved mapping, build a SELECT column list using only real,
    confirmed-present columns. Returns (select_clause, present_fields,
    unmapped_fields) — present_fields is the row-tuple order to zip results
    against; unmapped_fields is surfaced to the caller per §3.3, never
    silently dropped."""
    parts, present, unmapped = [], [], []
    for field in fields_wanted:
        col = mapping_fields[field]["column"]
        if col is None:
            unmapped.append(field)
            continue
        parts.append(f'"{col}" AS "{field}"')
        present.append(field)
    return ", ".join(parts), present, unmapped


def _row_to_dict(row: tuple, present_fields: list[str], unmapped_fields: list[str]) -> dict:
    rec = dict(zip(present_fields, row))
    for field in unmapped_fields:
        rec[field] = None
    return rec


def _require_confirmed(mapping: dict) -> Optional[dict]:
    """§3.4: writes may not guess. A mapping's heuristic fields are fine for
    reads but must be explicitly confirmed (schema_confirm_mapping) before
    any write tool may use them."""
    if not mapping.get("confirmed"):
        return {
            "error": (
                f"unconfirmed_schema: table '{mapping.get('table')}' has not been confirmed "
                "for this database — call schema_confirm_mapping, or edit the mapping file "
                "directly, then retry"
            )
        }
    return None


def _write_param(field_mapping: dict, value):
    """jsonb/json target columns need their Python value wrapped so psycopg2
    adapts it as JSON rather than a plain string."""
    if field_mapping.get("data_type") in ("jsonb", "json"):
        return Json(value)
    return value


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
    """Central pipeline: sanitize -> gate -> rate check -> dispatch -> receipt.

    Gate runs before the rate check specifically so an invalid/unmanifested
    app_id is rejected (via gate.permitted -> _validate_app_id) before it can
    ever be used as a _buckets dict key — an unvalidated app_id string must
    never reach _check_rate, or a caller can grow _buckets unbounded with
    arbitrary strings (L-DOS-01).

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

            # effective_app_id is the identity gate actually authorized this
            # call under — in serve mode this is the bound identity, NOT
            # necessarily call_kwargs["app_id"] (see _gate / L-AUTH-02). Every
            # downstream step (rate limit, dispatch, receipt) uses it instead
            # of the raw caller-supplied app_id.
            effective_app_id, gate_err = _gate(app_id, tool_name)
            if gate_err:
                _receipt_log.record(app_id, tool_name, "denied", gate_err.get("error"))
                return _shape(gate_err)
            if "app_id" in call_kwargs:
                call_kwargs["app_id"] = effective_app_id

            allowed, retry_after = _check_rate(effective_app_id)
            if not allowed:
                _receipt_log.record(effective_app_id, tool_name, "rate_limited", f"retry_after={retry_after}")
                return _shape({"error": "rate_limited", "retry_after": retry_after})

            try:
                result = fn(**call_kwargs)
            except Exception as e:
                _receipt_log.record(effective_app_id, tool_name, "error", f"{type(e).__name__}: {e}")
                raise

            probe = (result[0] if (isinstance(result, list) and result
                                    and isinstance(result[0], dict)) else result)
            if isinstance(probe, dict) and "error" in probe:
                _receipt_log.record(effective_app_id, tool_name, "error", str(probe["error"]))
            else:
                _receipt_log.record(effective_app_id, tool_name, "ok", None)

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

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed
    fields = mapping["fields"]
    if fields["id"]["column"] is None or fields["content"]["column"] is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' or 'content' column"}

    kid = str(uuid.uuid4())[:8].upper()
    values = {"id": kid, "content": content}
    if fields["domain"]["column"]:
        values["domain"] = domain
    if fields["source"]["column"]:
        values["source"] = source
    if fields["tags"]["column"]:
        values["tags"] = tags or []

    cols = ", ".join(f'"{fields[f]["column"]}"' for f in values)
    placeholders = ", ".join(["%s"] * len(values))
    params = [_write_param(fields[f], v) for f, v in values.items()]
    cur = pg.cursor()
    cur.execute(
        f"INSERT INTO knowledge ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        params,
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
    tokens = query.split()
    if not tokens:
        return {"results": []}
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    if fields["id"]["column"] is None or fields["content"]["column"] is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' or 'content' column"}

    select_clause, present, unmapped = _build_select(_KNOWLEDGE_FIELDS, fields)
    content_ref = sp.cast_for_ilike(fields["content"])
    conditions = " AND ".join([f"{content_ref} ILIKE %s"] * len(tokens))
    params: list = [f"%{t}%" for t in tokens]
    sql = f"SELECT {select_clause} FROM knowledge WHERE {conditions}"
    if domain and fields["domain"]["column"]:
        sql += f' AND "{fields["domain"]["column"]}" = %s'
        params.append(domain)
    sql += " LIMIT %s"
    params.append(limit)

    cur = pg.cursor()
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()

    result = {"results": [_row_to_dict(r, present, unmapped) for r in rows]}
    if unmapped:
        result["_unmapped"] = unmapped
    return result


# ── Task queue tools ───────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("task_submit")
def task_submit(app_id: str, task: str, agent: str = "kart") -> dict:
    """Submit a task to the Kart sandboxed execution queue. Returns task_id for polling."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed
    fields = mapping["fields"]
    if fields["task_id"]["column"] is None or fields["task"]["column"] is None:
        return {"error": "schema_unusable: 'tasks' table has no mappable 'task_id' or 'task' column"}

    import random
    task_id = "".join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ0123456789", k=8))
    values = {"task_id": task_id, "task": task}
    if fields["submitted_by"]["column"]:
        values["submitted_by"] = app_id or "willow-mcp"
    if fields["agent"]["column"]:
        values["agent"] = agent

    cols = ", ".join(f'"{fields[f]["column"]}"' for f in values)
    placeholders = ", ".join(["%s"] * len(values))
    params = [_write_param(fields[f], v) for f, v in values.items()]
    cur = pg.cursor()
    cur.execute(f"INSERT INTO tasks ({cols}) VALUES ({placeholders})", params)
    cur.close()
    return {"task_id": task_id, "status": "pending"}


@mcp.tool()
@_guarded("task_status")
def task_status(app_id: str, task_id: str) -> dict:
    """Poll the status of a submitted Kart task. Returns status, result, and completion time."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    id_col = fields["task_id"]["column"]
    if id_col is None:
        return {"error": "schema_unusable: 'tasks' table has no mappable 'task_id' column"}

    select_clause, present, unmapped = _build_select(_TASK_FIELDS, fields)
    cur = pg.cursor()
    cur.execute(f'SELECT {select_clause} FROM tasks WHERE "{id_col}" = %s', (task_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"error": "not_found"}

    result = _row_to_dict(row, present, unmapped)
    if unmapped:
        result["_unmapped"] = unmapped
    return result


@mcp.tool()
@_guarded("task_list")
def task_list(app_id: str, agent: str = "kart", limit: int = 10) -> dict:
    """List pending tasks in the Kart queue."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    id_col, status_col, agent_col = (fields["task_id"]["column"], fields["status"]["column"],
                                      fields["agent"]["column"])
    if id_col is None or status_col is None or agent_col is None:
        return {"error": "schema_unusable: 'tasks' table has no mappable 'task_id', 'status', or 'agent' column"}

    listed_fields = ["task_id", "task", "submitted_by", "created_at"]
    select_clause, present, unmapped = _build_select(listed_fields, fields)
    cur = pg.cursor()
    cur.execute(
        f'SELECT {select_clause} FROM tasks WHERE "{status_col}" = \'pending\' AND "{agent_col}" = %s '
        f'ORDER BY "{fields["created_at"]["column"] or id_col}" LIMIT %s',
        (agent, limit)
    )
    rows = cur.fetchall()
    cur.close()
    pending = [_row_to_dict(r, present, unmapped) for r in rows]
    for p in pending:
        if p.get("task"):
            p["task"] = p["task"][:80]
    result = {"pending": pending}
    if unmapped:
        result["_unmapped"] = unmapped
    return result


# ── Knowledge extension tools ──────────────────────────────────────────────────

@mcp.tool()
@_guarded("kb_at")
def kb_at(app_id: str, atom_id: str) -> dict:
    """Fetch a single knowledge atom by ID. Returns the full atom or {error: not_found}."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    id_col = fields["id"]["column"]
    if id_col is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' column"}

    select_clause, present, unmapped = _build_select(_KNOWLEDGE_FIELDS, fields)
    cur = pg.cursor()
    cur.execute(f'SELECT {select_clause} FROM knowledge WHERE "{id_col}" = %s', (atom_id,))
    row = cur.fetchone()
    cur.close()
    if not row:
        return {"error": "not_found"}

    result = _row_to_dict(row, present, unmapped)
    if unmapped:
        result["_unmapped"] = unmapped
    return result


@mcp.tool()
@_guarded("kb_promote")
def kb_promote(app_id: str, atom_id: str, domain: str) -> dict:
    """Change the domain of an existing knowledge atom."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed
    fields = mapping["fields"]
    id_col, domain_col = fields["id"]["column"], fields["domain"]["column"]
    if id_col is None or domain_col is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' or 'domain' column"}

    cur = pg.cursor()
    cur.execute(f'UPDATE knowledge SET "{domain_col}" = %s WHERE "{id_col}" = %s', (domain, atom_id))
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

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed
    fields = mapping["fields"]
    if fields["id"]["column"] is None or fields["content"]["column"] is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' or 'content' column"}

    kid = str(uuid.uuid4())[:8].upper()
    all_tags = list(set(["journal"] + (tags or [])))
    values = {"id": kid, "content": content}
    if fields["domain"]["column"]:
        values["domain"] = "journal"
    if fields["source"]["column"]:
        values["source"] = source
    if fields["tags"]["column"]:
        values["tags"] = all_tags

    cols = ", ".join(f'"{fields[f]["column"]}"' for f in values)
    placeholders = ", ".join(["%s"] * len(values))
    params = [_write_param(fields[f], v) for f, v in values.items()]
    cur = pg.cursor()
    cur.execute(
        f"INSERT INTO knowledge ({cols}) VALUES ({placeholders}) ON CONFLICT DO NOTHING",
        params,
    )
    cur.close()
    return {"id": kid, "domain": "journal"}


@mcp.tool()
@_guarded("schema_confirm_mapping")
def schema_confirm_mapping(app_id: str, table: str, overrides: Optional[dict] = None) -> dict:
    """Confirm a table's schema mapping, unlocking write tools for it (knowledge_ingest,
    kb_journal, kb_promote today). `overrides` lets you correct individual
    canonical-field -> real-column assignments before confirming, e.g.
    {"source": "origin_ref"} or {"tags": null} to explicitly mark a field
    unmapped. Gated separately from knowledge_write — confirming a mapping
    is a more consequential act than a single write."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    canonical_fields = _CONFIRMABLE_TABLES.get(table)
    if canonical_fields is None:
        return {
            "error": f"unknown_table: '{table}' is not a table willow-mcp knows how to map "
                     f"(known: {sorted(_CONFIRMABLE_TABLES)})"
        }
    return sp.confirm(pg, app_id, table, canonical_fields, overrides=overrides)


@mcp.tool()
@_guarded("kb_startup_continuity")
def kb_startup_continuity(app_id: str, limit: int = 20) -> dict:
    """Fetch knowledge atoms tagged or domained for startup continuity."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    fields = mapping["fields"]
    id_col, domain_col, tags_col = (fields["id"]["column"], fields["domain"]["column"],
                                     fields["tags"]["column"])
    if id_col is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' column"}

    select_clause, present, unmapped = _build_select(_KNOWLEDGE_FIELDS, fields)
    where_parts, params = [], []
    if domain_col:
        where_parts.append(f'"{domain_col}" = %s')
        params.append("continuity")
    if tags_col:
        where_parts.append(f'"{tags_col}" LIKE %s')
        params.append('%"continuity"%')
    # No 'domain' or 'tags' mapping at all -> nothing to filter continuity by;
    # fail closed to an empty set rather than silently returning every atom.
    if not where_parts:
        return {"atoms": [], "_unmapped": unmapped,
                "_note": "neither 'domain' nor 'tags' is mapped on this table — "
                         "cannot identify continuity atoms"}
    where_sql = " OR ".join(where_parts)
    params.append(limit)

    cur = pg.cursor()
    cur.execute(f'SELECT {select_clause} FROM knowledge WHERE {where_sql} '
                f'ORDER BY "{id_col}" DESC LIMIT %s', params)
    rows = cur.fetchall()
    cur.close()

    result = {"atoms": [_row_to_dict(r, present, unmapped) for r in rows]}
    if unmapped:
        result["_unmapped"] = unmapped
    return result


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

    mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
    if "error" in mapping:
        return mapping
    status_col = mapping["fields"]["status"]["column"]
    if status_col is None:
        return {"error": "schema_unusable: 'tasks' table has no mappable 'status' column"}

    try:
        cur = pg.cursor()
        cur.execute(f'SELECT "{status_col}", COUNT(*) FROM tasks GROUP BY "{status_col}"')
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

def _cmd_setup(args) -> None:
    """`willow-mcp setup` — write OAuth provider credentials to the vault.

    Secrets are only ever accepted via getpass/stdin prompt when the
    corresponding CLI flag is omitted, so a client-secret or private key
    never has to appear in shell history or a process listing.
    """
    import getpass
    import sys

    from .vault import default_vault

    vault = default_vault()
    did_anything = False

    if args.google_client_id:
        did_anything = True
        vault.write("google.client_id", args.google_client_id)
        secret = args.google_client_secret or getpass.getpass("Google client secret: ")
        vault.write("google.client_secret", secret)
        print("Google credentials written to vault.")

    if args.apple_team_id:
        did_anything = True
        vault.write("apple.team_id", args.apple_team_id)
        vault.write("apple.client_id", args.apple_client_id or "")
        vault.write("apple.key_id", args.apple_key_id or "")
        if args.apple_p8_key_path:
            with open(args.apple_p8_key_path) as f:
                p8_key = f.read()
        else:
            print("Paste the Apple .p8 private key contents, then press Ctrl-D:")
            p8_key = sys.stdin.read()
        vault.write("apple.p8_key", p8_key)
        print("Apple credentials written to vault.")

    if not did_anything:
        print("Nothing to do — pass --google-client-id and/or --apple-team-id.")


def _cmd_confirm_binding(args) -> None:
    """`willow-mcp confirm-binding` — bind a signed-in OAuth identity to an app_id.

    Local/stdio-only by design (L-AUTH-02): this is never reachable as an MCP
    tool, so a remote serve-mode caller can never confirm their own binding.
    Run this on the host after the person has signed in once via the OAuth
    approval page (which creates the unconfirmed binding record).
    """
    from .identity_binding import confirm_binding

    try:
        record = confirm_binding(args.issuer, args.subject, args.app_id)
    except ValueError as e:
        print(f"Error: {e}")
        raise SystemExit(1)
    print(f"Bound ({record['issuer']}, {record['subject_id']}) -> app_id={record['app_id']!r} "
          f"(email: {record.get('email')}, basis: {record.get('email_basis', 'unknown')})")
    if record.get("email_drift"):
        print(f"  WARNING: email changed since this binding was first proposed "
              f"({record.get('drift_from_email')} -> {record.get('drift_to_email')}) "
              f"at {record.get('email_drift_detected_at')} — verify this is still the same person "
              f"before confirming.")


def main():
    import argparse
    parser = argparse.ArgumentParser(prog="willow-mcp")
    parser.add_argument("--serve", action="store_true", help="Run as HTTP server with OAuth")
    parser.add_argument("--port", type=int, default=_PORT)
    parser.add_argument("--host", default=_HOST)
    subparsers = parser.add_subparsers(dest="command")

    setup_p = subparsers.add_parser("setup", help="Write OAuth provider credentials to the vault")
    setup_p.add_argument("--google-client-id")
    setup_p.add_argument("--google-client-secret", help="Omit to be prompted (recommended)")
    setup_p.add_argument("--apple-team-id")
    setup_p.add_argument("--apple-client-id")
    setup_p.add_argument("--apple-key-id")
    setup_p.add_argument("--apple-p8-key-path", help="Path to the .p8 private key file; omit to paste via stdin")

    confirm_p = subparsers.add_parser(
        "confirm-binding",
        help="Bind a signed-in OAuth identity to an app_id (local, stdio-only — never an MCP tool)",
    )
    confirm_p.add_argument("--issuer", required=True, choices=["google", "apple"])
    confirm_p.add_argument("--subject", required=True, help="The IdP 'sub' claim for this identity")
    confirm_p.add_argument("--app-id", required=True, dest="app_id")

    args, _ = parser.parse_known_args()

    if args.command == "setup":
        _cmd_setup(args)
        return
    if args.command == "confirm-binding":
        _cmd_confirm_binding(args)
        return

    if args.serve or _SERVE_MODE:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
