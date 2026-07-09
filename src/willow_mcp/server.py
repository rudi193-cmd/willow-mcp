"""
willow-mcp MCP server — agent-neutral core tools.

Modes:
  stdio (default):  python3 -m willow_mcp
  serve (HTTP):     python3 -m willow_mcp --serve [--port 8765] [--host 127.0.0.1]

Tools:
  Store (SQLite):  store_put, store_get, store_list, store_update, store_search,
                   store_delete, store_search_all
  Knowledge (PG):  knowledge_ingest, knowledge_search, kb_ingest,
                   kb_at, kb_promote, kb_journal, kb_startup_continuity
  Tasks (PG):      task_submit, task_status, task_list
  Agent (PG):      agent_route, agent_dispatch_result
  Dispatch (FS):   dispatch_send, dispatch_read, dispatch_list, dispatch_accept,
                   handoff_write_v4, handoff_read, verify_handoff, agent_clear,
                   session_read, session_enter, session_handoff_write
  Registry:        specialist_list, specialist_get, agent_seed_mirror,
                   exposure_config_get, exposure_slice
  Fleet (PG):      fleet_status, fleet_health
  Context (SQLite):context_save, context_get, context_list, context_expire
  Integrations:    integration_list, integration_status, integration_call
  Audit (SQLite):  receipts_tail
  Diagnostic:      diagnostic_summary (ungated self-check)

Auth (stdio): manifest-based per-tool ACL — app_id required on every call.
  Exception: diagnostic_summary is ungated (must answer when a manifest is broken).
Auth (serve): OAuth 2.0 PKCE (Google / Apple) + per-tool ACL gate.
Fail-closed: no manifest = all calls denied.

Security (Phase 4): every tool call runs gate -> sanitize -> rate-check ->
dispatch -> receipt, via the _guarded() decorator. See _gate, _sanitize,
_check_rate, and receipts.ReceiptLog.
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
from datetime import datetime, timezone
from functools import wraps
from pathlib import Path
from typing import Any, Optional

from mcp.server.fastmcp import FastMCP
from psycopg2.extras import Json

from .db import Store, get_pg
from .gate import permitted
from .identity_binding import resolve_app_id
from .receipts import ReceiptLog
from . import paths
from . import schema_profile as sp
from . import dispatch as dispatch_stack
from . import handoff as handoff_stack
from . import gaps as gap_backlog

_store = Store()
_receipt_log = ReceiptLog()

def _argv_opt(flag: str) -> Optional[str]:
    """Read `--flag value` or `--flag=value` from sys.argv at import time.

    The FastMCP object, base URL, and OAuth issuer are all built at import —
    before main()'s argparse runs — so the CLI host/port must be resolved here
    or the flags are silently ignored (only the env vars would take effect).
    """
    for i, arg in enumerate(sys.argv):
        if arg == flag and i + 1 < len(sys.argv):
            return sys.argv[i + 1]
        if arg.startswith(flag + "="):
            return arg.split("=", 1)[1]
    return None


# Precedence: CLI flag > env var > default.
_PORT = int(_argv_opt("--port") or os.getenv("WILLOW_MCP_PORT", "8765"))
_HOST = _argv_opt("--host") or os.getenv("WILLOW_MCP_HOST", "127.0.0.1")
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

    from .human_session import orchestrator_write_denial

    human_denial = orchestrator_write_denial(effective, tool_name, serve_mode=_SERVE_MODE)
    if human_denial:
        return None, {"error": human_denial}

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
    for key in ("record", "context", "value", "body"):
        val = kwargs.get(key)
        if isinstance(val, dict):
            size = len(json.dumps(val))
            if size > _MAX_BLOB_BYTES:
                return kwargs, f"'{key}' exceeds 512KB limit ({size} bytes)"

    for key in ("content", "task", "query", "question", "answer", "topic"):
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

    for key in ("tags", "sources"):
        items = kwargs.get(key)
        if isinstance(items, list):
            if len(items) > _MAX_TAGS:
                return kwargs, f"'{key}' exceeds max {_MAX_TAGS} items"
            for item in items:
                if isinstance(item, str) and len(item) > _MAX_TAG_LEN:
                    return kwargs, f"'{key}' item exceeds max {_MAX_TAG_LEN} chars"

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
    """Central pipeline: gate -> sanitize -> rate check -> dispatch -> receipt.

    Gate runs first (B-16) so an unpermitted caller gets a clean permission
    denial as the very first signal, rather than a sanitizer error for a call
    it was never allowed to make. Gate also validates the app_id shape (via
    gate.permitted -> _validate_app_id), so an invalid/unmanifested app_id is
    rejected before it can reach _sanitize or ever be used as a _buckets dict
    key — an unvalidated app_id string must never reach _check_rate, or a
    caller can grow _buckets unbounded with arbitrary strings (L-DOS-01).

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

            # effective_app_id is the identity gate actually authorized this
            # call under — in serve mode this is the bound identity, NOT
            # necessarily call_kwargs["app_id"] (see _gate / L-AUTH-02). Every
            # downstream step (sanitize, rate limit, dispatch, receipt) uses it
            # instead of the raw caller-supplied app_id.
            #
            # Gate runs BEFORE sanitize (B-16): an unpermitted caller is denied
            # up front, so it never reaches the sanitizer. A denial is the first
            # signal, not a sanitize error for a call that was never allowed.
            effective_app_id, gate_err = _gate(app_id, tool_name)
            if gate_err:
                _receipt_log.record(app_id, tool_name, "denied", gate_err.get("error"))
                return _shape(gate_err)
            if "app_id" in call_kwargs:
                call_kwargs["app_id"] = effective_app_id

            cleaned, problem = _sanitize(call_kwargs)
            if problem:
                _receipt_log.record(effective_app_id, tool_name, "error", f"sanitize: {problem}")
                return _shape({"error": f"sanitize: {problem}"})
            call_kwargs = cleaned

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
#
# Collection-level scoping (B-24 / SECURITY_AUDIT.md L-ISO-01): the SOIL store
# shares the wider Willow fleet's store by default (WILLOW_STORE_ROOT) — a
# default, not a design commitment; point it elsewhere and diagnostic_summary's
# `severance` check confirms the cut — store_* tools have no isolation unless
# an app's manifest opts in via a `store_scope` list (gate.store_scope /
# gate.collection_permitted). Unscoped apps keep today's unrestricted access;
# this only closes the gap for apps an operator explicitly chooses to confine.

def _collection_denied(app_id: str, collection: str) -> dict:
    return {"error": (
        f"collection_denied: '{collection}' is outside this app's store_scope "
        f"in $WILLOW_HOME/mcp_apps/{app_id or '<app_id>'}/manifest.json")}


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
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return _collection_denied(app_id, collection)
    rid, action = _store.put(collection, record, record_id=record_id, deviation=deviation)
    return {"id": rid, "action": action}


@mcp.tool()
@_guarded("store_get")
def store_get(app_id: str, collection: str, record_id: str) -> dict:
    """Read a single record by ID. Returns the record or {error: not_found}."""
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return _collection_denied(app_id, collection)
    item = _store.get(collection, record_id)
    return item or {"error": "not_found"}


@mcp.tool()
@_guarded("store_list", list_error=True)
def store_list(app_id: str, collection: str) -> list:
    """Return every record in a collection (unfiltered). Prefer store_search for large collections."""
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return [_collection_denied(app_id, collection)]
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
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return _collection_denied(app_id, collection)
    rid = _store.update(collection, record_id, record, deviation=deviation)
    return {"id": rid} if rid else {"error": "not_found"}


@mcp.tool()
@_guarded("store_search", list_error=True)
def store_search(app_id: str, collection: str, query: str) -> list:
    """Full-text search within a single collection (AND logic across tokens)."""
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return [_collection_denied(app_id, collection)]
    return _store.search(collection, query)


@mcp.tool()
@_guarded("store_delete")
def store_delete(app_id: str, collection: str, record_id: str) -> dict:
    """Soft-delete a record — invisible to get/search but retained in audit trail."""
    from . import gate
    if not gate.collection_permitted(app_id, collection):
        return _collection_denied(app_id, collection)
    deleted = _store.delete(collection, record_id)
    return {"deleted": deleted}


@mcp.tool()
@_guarded("store_search_all", list_error=True)
def store_search_all(app_id: str, query: str) -> list:
    """Search across ALL SOIL collections (or only this app's store_scope, if it has one). Use when the collection is unknown."""
    from . import gate
    return _store.search_all(query, scope=gate.store_scope(app_id))


# ── Knowledge tools ────────────────────────────────────────────────────────────

def _knowledge_ingest_core(
    app_id: str,
    content: str,
    domain: str = "general",
    source: str = "",
    tags: Optional[list] = None,
) -> dict:
    """The actual knowledge-base write, shared by knowledge_ingest and
    gap_promote. Deliberately ungated (no @_guarded, no receipt of its
    own) — callers are tools already gated under their own name, and
    routing both through one _guarded("knowledge_ingest") wrapper would
    force gap_promote callers to also hold knowledge_ingest permission and
    would double the receipt/rate-limit accounting for one logical write.
    The schema-confirmation requirement below is the real gate either way:
    unconfirmed, this refuses to write regardless of caller."""
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
@_guarded("knowledge_ingest")
def knowledge_ingest(
    app_id: str,
    content: str,
    domain: str = "general",
    source: str = "",
    tags: Optional[list] = None,
) -> dict:
    """Add a knowledge atom to the Postgres knowledge base. Check for duplicates first."""
    return _knowledge_ingest_core(app_id, content, domain=domain, source=source, tags=tags)


# ── Gap backlog tools ──────────────────────────────────────────────────────────
#
# "What don't we know yet" — a fleet-wide backlog (core/gaps.py), not scoped
# to app_id, the same way knowledge_search/store_search_all are shared by
# default. gap_log/list/resolve work SOIL-only (no Postgres needed);
# gap_promote is the one write that reaches the knowledge base, and it does
# so through the exact same schema-confirmation gate as knowledge_ingest.

@mcp.tool()
@_guarded("gap_log")
def gap_log(app_id: str, topic: str, question: str) -> dict:
    """Log or bump a "we don't know this yet" entry. Repeated asks of the
    same topic+question increment asked_count instead of duplicating —
    asked_count is the backlog's own priority signal for what to fill in
    next. Returns {id, status, asked_count}."""
    return gap_backlog.log(topic, question)


@mcp.tool()
@_guarded("gap_list", list_error=True)
def gap_list(
    app_id: str,
    topic: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50,
) -> list:
    """List gaps, most-asked first. Filter by topic and/or status
    (open | resolved | promoted)."""
    return gap_backlog.list_gaps(topic=topic, status=status, limit=limit)


@mcp.tool()
@_guarded("gap_resolve")
def gap_resolve(app_id: str, gap_id: str, note: str = "") -> dict:
    """Mark a gap as being worked or answered — bookkeeping only, does not
    write to the knowledge base. Use gap_promote to actually land a
    verified answer and close the gap out."""
    return gap_backlog.resolve(gap_id, note=note)


@mcp.tool()
@_guarded("gap_promote")
def gap_promote(
    app_id: str,
    gap_id: str,
    answer: str,
    sources: list,
    confirmed_by: str,
    domain: str = "general",
    tags: Optional[list] = None,
) -> dict:
    """Turn a gap into trusted knowledge. Requires an answer, at least one
    source, and who's vouching for it (confirmed_by) — a human name, an
    agent id, whatever this fleet uses as an identity, but never empty.
    Writes through the SAME schema-confirmation gate as a direct
    knowledge_ingest call: if the 'knowledge' table mapping for this app_id
    hasn't been confirmed via schema_confirm_mapping, this refuses with
    unconfirmed_schema exactly like knowledge_ingest would. Requires
    Postgres — gap_log/list/resolve work SOIL-only, but promotion targets
    the durable, searchable knowledge base. Gated as its own permission
    (gap_promote), separate from gap_write, the same way schema_admin is
    kept separate from knowledge_write — landing something as trusted
    knowledge is a more consequential act than logging or resolving a gap."""
    gap = gap_backlog.get(gap_id)
    if not gap:
        return {"error": "not_found"}
    if gap.get("status") == "promoted":
        return {"error": "already_promoted", "promoted_to": gap.get("promoted_to")}

    answer = (answer or "").strip()
    confirmed_by = (confirmed_by or "").strip()
    source_list = [str(s) for s in (sources or []) if str(s).strip()]
    if not answer or not source_list or not confirmed_by:
        return {"error": "answer, at least one source, and confirmed_by are required"}

    merged_tags = list(tags or []) + [f"confirmed_by:{confirmed_by}", f"gap:{gap_id}"]
    result = _knowledge_ingest_core(
        app_id,
        answer,
        domain=domain,
        source=", ".join(source_list),
        tags=merged_tags,
    )
    if "error" in result:
        return result
    gap_backlog.mark_promoted(gap_id, result["id"])
    return {"id": result["id"], "gap_id": gap_id, "promoted": True}


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
def task_submit(app_id: str, task: str, agent: str = "kart", allow_net: bool = False) -> dict:
    """Submit a task to the Kart sandboxed execution queue. Returns task_id for polling.

    Tasks run network-isolated by default. Egress needs THREE keys, all held at
    once: the 'task_net' capability in the app's manifest (it is NOT included in
    task_queue or full_access; grant it explicitly), the operator's standing
    `consent.internet` in $WILLOW_HOME/settings.global.json, and an unexpired
    egress **lease** issued by the operator via `willow-mcp grant-net`. The
    capability says *this app may ever request egress*; consent says *egress is
    permitted right now*, fleet-wide; the lease says *this app, until this time*.
    Only when all three hold is the Kart worker's `# allow_net` directive appended
    so the sandbox gets egress. No MCP tool can issue a lease.

    Task text is security-scanned at SUBMIT time (defense-in-depth): a task the
    Kart scanner would refuse — destructive, exfiltration, secret access, obfusc-
    ation, or resource-exhaustion (fork bomb / spin / disk-fill) — is rejected
    here before it ever occupies a queue slot, not only when the worker later
    picks it up. The worker re-scans at execution regardless; this just denies
    earlier and keeps a bomb from sitting `pending`.
    """
    # Submit-time scan, before any DB work — a dangerous task is refused even if
    # Postgres is down. kartikeya is a hard dependency, but degrade open (worker
    # still scans) rather than crash the tool if it is somehow unimportable.
    try:
        from kartikeya import check_kart_task
        blocked = check_kart_task(task or "")
    except Exception:
        blocked = None
    if blocked:
        return blocked

    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    if allow_net:
        from . import consent, gate, lease
        # Key 1: is this app allowed to ask at all? (capability, granted once)
        if not gate.permitted(app_id, gate.NET_PERMISSION):
            return {"error": (
                f"net_denied: allow_net requires the '{gate.NET_PERMISSION}' permission in "
                f"this app's manifest ($WILLOW_HOME/mcp_apps/{app_id or '<app_id>'}/manifest.json). "
                "It is not granted by task_queue or full_access — add it explicitly.")}
        # Key 2: does the operator permit egress right now? (standing consent)
        # Read fail-closed — an absent or unparseable policy is not consent.
        if not consent.internet_permitted():
            return {"error": (
                "consent_denied: allow_net also requires the operator's standing "
                f"'consent.internet' in {consent.settings_path()}. This app holds "
                f"'{gate.NET_PERMISSION}', but egress is switched off (or the consent "
                "policy could not be read, which denies). Only the operator may turn it "
                "on — an agent may request egress, never grant it to itself.")}
        # Key 3: has the operator issued a live lease for THIS app? (B-32)
        # A capability that never expires is indistinguishable from one that was
        # self-granted an hour ago; a lease has a clock and an issuer.
        lease_state = lease.read_lease(app_id)
        if lease_state["status"] != "active":
            return {"error": (
                f"lease_denied: allow_net requires an unexpired egress lease for '{app_id}' "
                f"(status: {lease_state['status']}"
                + (f" — {lease_state['error']}" if lease_state.get("error") else "")
                + "). Leases are issued only by the operator, on the host, via "
                f"`willow-mcp grant-net {app_id or '<app_id>'} --ttl 30m --reason ...`, and they "
                "expire. No MCP tool can mint one. Ask for a lease; do not write the file.")}
        # Whichever keys are within this process's own write reach are keys it
        # could have forged. Reported always; enforced only under strict mode,
        # because on a single-uid host that is every install (B-32 residual).
        if lease.strict_trust_root():
            forgeable = lease.self_writable_trust_paths(app_id)
            if forgeable:
                return {"error": (
                    "trust_root_denied: WILLOW_MCP_STRICT_TRUST_ROOT is set, but this "
                    "process can write the very keys that authorize it: "
                    + ", ".join(f"{f['key']} ({f['path']})" for f in forgeable)
                    + ". A confirm authority inside the actor's write reach is not an "
                    "authority. Chown these to a uid the agent does not run as.")}

    mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed
    fields = mapping["fields"]
    if fields["task_id"]["column"] is None or fields["task"]["column"] is None:
        return {"error": "schema_unusable: 'tasks' table has no mappable 'task_id' or 'task' column"}

    # The Kart worker (willow-2.0) reads network policy from directive lines
    # (`# allow_net` / `# allow_localhost`) in the stored task text
    # (core/kart_sandbox.py task_allows_network / task_allows_localhost, which
    # match on `line.strip() == <directive>`). Strip any such caller-supplied
    # line UNCONDITIONALLY first, then re-append `# allow_net` only when the
    # permission check above passed. Otherwise a caller holding only task_queue
    # could grant itself egress by embedding the directive in `task` text with
    # allow_net=False — the gate is keyed off the argument, not the text (B-21;
    # B-19 closed only the allow_net=True path).
    _NET_DIRECTIVES = {"# allow_net", "# allow_localhost"}
    task = "\n".join(
        line for line in task.splitlines() if line.strip() not in _NET_DIRECTIVES
    )
    if allow_net:
        task = task.rstrip("\n") + "\n# allow_net"

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
@_guarded("kb_ingest")
def kb_ingest(
    app_id: str,
    agent_id: str,
    slice: str = "",
    sensitivity: str = "sensitive",
    tier: str = "canonical",
    supersede: bool = True,
) -> dict:
    """Promote a ratified agent_seed slice to Postgres KB (source_type: agent_seed).

    Requires ratified + trusted seed at $WILLOW_HOME/seeds/{agent_id}.json.
    slice: voice_only | work_context | full (omit to use exposure.json default for kb_ingest).
    Never promotes persona.cast or context.personal_note.
    """
    from . import seed_kb as skb

    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}

    mapping = sp.resolve(pg, app_id, "knowledge", _KNOWLEDGE_FIELDS)
    if "error" in mapping:
        return mapping
    unconfirmed = _require_confirmed(mapping)
    if unconfirmed:
        return unconfirmed

    kid = str(uuid.uuid4())[:8].upper()
    return skb.promote_seed_to_kb(
        pg,
        mapping["fields"],
        agent_id=agent_id,
        slice_name=slice,
        sensitivity=sensitivity,
        tier=tier,
        supersede=supersede,
        new_id=kid,
    )


@mcp.tool()
@_guarded("schema_confirm_mapping")
def schema_confirm_mapping(app_id: str, table: str, overrides: Optional[dict] = None,
                           preview: bool = False) -> dict:
    """Confirm a table's schema mapping, unlocking write tools for it (knowledge_ingest,
    kb_journal, kb_promote today). `overrides` lets you correct individual
    canonical-field -> real-column assignments before confirming, e.g.
    {"source": "origin_ref"} or {"tags": null} to explicitly mark a field
    unmapped. Gated separately from knowledge_write — confirming a mapping
    is a more consequential act than a single write.

    preview=True: dry-run — return the proposed mapping AND a rendered `sample`
    row (what each canonical field actually resolves to) WITHOUT confirming or
    writing. Review the sample first: a column that name-matches but holds the
    wrong data — e.g. a `content` column that is really a provenance blob, with
    the real text in `title`/`summary` — reveals itself in the sample where a
    name match cannot. preview=False (default): confirm, and include the sample
    in the response so the confirmation is never blind."""
    pg = get_pg()
    if not pg:
        return {"error": "postgres_unavailable"}
    canonical_fields = _CONFIRMABLE_TABLES.get(table)
    if canonical_fields is None:
        return {
            "error": f"unknown_table: '{table}' is not a table willow-mcp knows how to map "
                     f"(known: {sorted(_CONFIRMABLE_TABLES)})"
        }
    if preview:
        return sp.preview(pg, app_id, table, canonical_fields, overrides=overrides)
    result = sp.confirm(pg, app_id, table, canonical_fields, overrides=overrides)
    if isinstance(result, dict) and "error" not in result:
        result["sample"] = sp.render_sample(pg, table, result.get("fields", {}))
    return result


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
    id_col = fields["id"]["column"]
    domain_col = fields["domain"]["column"]
    tags_col = fields["tags"]["column"]
    if id_col is None:
        return {"error": "schema_unusable: 'knowledge' table has no mappable 'id' column"}

    # 'tags' often has no top-level column: on willow-style schemas the tags
    # live inside a jsonb metadata/provenance blob physically named 'content'
    # — which is NOT the canonical 'content' field (that maps to the
    # human-readable 'summary'; the jsonb blob is deliberately unmapped, B-10).
    # Discover a jsonb 'content' column by introspection rather than assuming
    # one, and read continuity tags from content->'tags' (a string array,
    # e.g. ["release-process","ci"]). Only consulted when there is no
    # top-level tags column to filter on.
    tags_jsonb_col = None
    if tags_col is None:
        jsonb_cols = {c.name for c in sp.introspect(pg, "knowledge")
                      if c.data_type in ("jsonb", "json")}
        if "content" in jsonb_cols:
            tags_jsonb_col = "content"

    select_clause, present, unmapped = _build_select(_KNOWLEDGE_FIELDS, fields)
    where_parts, params, filters = [], [], []
    if domain_col:
        where_parts.append(f'"{domain_col}" = %s')
        params.append("continuity")
        filters.append(f"{domain_col}='continuity'")
    if tags_col:
        where_parts.append(f'"{tags_col}" LIKE %s')
        params.append('%"continuity"%')
        filters.append(f"{tags_col} LIKE '\"continuity\"'")
    elif tags_jsonb_col:
        where_parts.append(f'"{tags_jsonb_col}"->\'tags\' @> %s::jsonb')
        params.append('["continuity"]')
        filters.append(f'{tags_jsonb_col}->tags @> ["continuity"]')

    # No way to identify continuity atoms on this schema (no domain, no tags
    # column, no jsonb content blob) -> fail loud with an explanatory empty
    # rather than a silent [] that reads as "nothing to continue".
    if not where_parts:
        return {"atoms": [], "_unmapped": unmapped,
                "_note": "cannot identify continuity atoms on this schema — none of "
                         "'domain', a top-level 'tags' column, or a jsonb 'content' "
                         "blob is available to filter on"}
    where_sql = " OR ".join(where_parts)
    params.append(limit)

    cur = pg.cursor()
    cur.execute(f'SELECT {select_clause} FROM knowledge WHERE {where_sql} '
                f'ORDER BY "{id_col}" DESC LIMIT %s', params)
    rows = cur.fetchall()
    cur.close()

    # _continuity_filter is always present so an empty result is legible: it
    # says exactly WHAT was searched, distinguishing "genuinely nothing to
    # continue" from "the query couldn't target this schema" (B-15 fail-loud).
    result = {"atoms": [_row_to_dict(r, present, unmapped) for r in rows],
              "_continuity_filter": filters}
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


# ── Dispatch packet stack (filesystem — no Postgres required) ─────────────────

@mcp.tool()
@_guarded("dispatch_send")
def dispatch_send(
    app_id: str,
    to_app: str,
    assignment_md: str,
    role: str = "",
    reply_to: str = "willow",
    summary: str = "",
    phase: str = "operate",
    priority: str = "normal",
    context_refs: Optional[list] = None,
) -> dict:
    """Create a dispatch packet: meta.json + assignment.md + status pending under $WILLOW_HOME/dispatch/."""
    return dispatch_stack.dispatch_send(
        from_app=app_id,
        to_app=to_app,
        assignment_md=assignment_md,
        role=role,
        reply_to=reply_to,
        summary=summary,
        phase=phase,
        priority=priority,
        context_refs=context_refs,
    )


@mcp.tool()
@_guarded("dispatch_read")
def dispatch_read(app_id: str, dispatch_id: str) -> dict:
    """Read dispatch meta, status, and assignment.md body."""
    return dispatch_stack.dispatch_read(dispatch_id)


@mcp.tool()
@_guarded("dispatch_list")
def dispatch_list(
    app_id: str,
    to_app: str = "",
    from_app: str = "",
    status: str = "",
    limit: int = 20,
) -> dict:
    """List dispatch packets, newest first."""
    return dispatch_stack.dispatch_list(
        to_app=to_app, from_app=from_app, status=status, limit=limit
    )


@mcp.tool()
@_guarded("dispatch_accept")
def dispatch_accept(
    app_id: str,
    dispatch_id: str,
    session_id: str = "",
) -> dict:
    """Specialist accepts packet: pending → working."""
    return dispatch_stack.dispatch_accept(dispatch_id, app_id, session_id)


@mcp.tool()
@_guarded("handoff_write_v4")
def handoff_write_v4(
    app_id: str,
    dispatch_id: str,
    findings: Optional[list] = None,
    narrative: str = "",
    checklist_resolved: bool = True,
    envelope_clean: bool = True,
) -> dict:
    """Complete dispatch work — writes handoff.json + closeout.md, status → complete."""
    return handoff_stack.handoff_write_v4(
        app_id,
        dispatch_id,
        findings=findings,
        narrative=narrative,
        checklist_resolved=checklist_resolved,
        envelope_clean=envelope_clean,
    )


@mcp.tool()
@_guarded("handoff_read")
def handoff_read(app_id: str, dispatch_id: str) -> dict:
    """Read structured handoff and closeout markdown for a dispatch."""
    return handoff_stack.handoff_read(dispatch_id)


@mcp.tool()
@_guarded("verify_handoff")
def verify_handoff(app_id: str, dispatch_id: str) -> dict:
    """Orchestrator verifies complete handoff — checklist, envelope, findings."""
    return handoff_stack.verify_handoff(dispatch_id)


@mcp.tool()
@_guarded("agent_clear")
def agent_clear(
    app_id: str,
    target_app: str,
    dispatch_id: str,
    session_id: str = "",
) -> dict:
    """Clear specialist after verified handoff — ready for next packet."""
    return dispatch_stack.agent_clear(target_app, dispatch_id, session_id)


@mcp.tool()
@_guarded("session_read")
def session_read(app_id: str, session_id: str) -> dict:
    """Read thin session state file for an app/session pair."""
    return dispatch_stack.session_read(app_id, session_id)


@mcp.tool()
@_guarded("session_enter")
def session_enter(
    app_id: str,
    session_id: str,
    dispatch_id: str = "",
) -> dict:
    """Resolve entry mode: human prompt (no id) vs dispatch id path (assignment + v4 closeout)."""
    return dispatch_stack.session_enter(app_id, session_id, dispatch_id)


@mcp.tool()
@_guarded("session_handoff_write")
def session_handoff_write(
    app_id: str,
    session_id: str,
    narrative: str,
    summary: str = "",
    findings: Optional[list] = None,
    next_bite: str = "",
) -> dict:
    """Human-entry session closeout — markdown handoff, no dispatch_id."""
    return dispatch_stack.session_handoff_write(
        app_id,
        session_id,
        narrative=narrative,
        summary=summary,
        findings=findings,
        next_bite=next_bite,
    )


# ── Specialist registry (desk) ───────────────────────────────────────────────

@mcp.tool()
@_guarded("specialist_list")
def specialist_list(app_id: str, include_permissions: bool = False) -> dict:
    """List specialists from config/specialists.json (orchestrator desk / routing)."""
    from . import registry as reg

    return {
        "registry": str(reg.registry_path()),
        "specialists": reg.list_specialists(include_permissions=include_permissions),
        "total": len(reg.list_specialists(include_permissions=False)),
    }


@mcp.tool()
@_guarded("specialist_get")
def specialist_get(app_id: str, agent_id: str, include_permissions: bool = True) -> dict:
    """Fetch one specialist registry row by agent_id."""
    from . import registry as reg

    row = reg.get_specialist(agent_id, include_permissions=include_permissions)
    if not row:
        return {"error": "not_found", "agent_id": agent_id}
    persona = reg.read_persona_text(agent_id)
    if persona is not None:
        row["persona"] = persona
        path = reg.resolve_persona_path(agent_id)
        row["persona_file"] = str(path) if path else None
    return row


@mcp.tool()
@_guarded("exposure_config_get")
def exposure_config_get(app_id: str) -> dict:
    """Read standing exposure defaults ($WILLOW_HOME/config/exposure.json, AS-8)."""
    from . import exposure as exp
    from .paths import exposure_config_path, willow_home

    path = exposure_config_path()
    cfg = exp.load_exposure_config()
    return {
        "format": exp.EXPOSURE_FORMAT,
        "path": str(path.relative_to(willow_home())) if path.is_file() else None,
        "exists": path.is_file(),
        "config": cfg,
    }


@mcp.tool()
@_guarded("exposure_slice")
def exposure_slice(
    app_id: str,
    agent_id: str,
    destination: str = "session_enter",
    preset: str = "",
    fields: list[str] | None = None,
) -> dict:
    """Resolve and apply an exposure preset for a seed destination (AS-8).

    destination: session_enter | kb_ingest | agent_seed_mirror | grove | cloud_llm | dispatch.
    preset: override standing default. fields: custom dotted paths (checkbox IDs).
    """
    from . import exposure as exp

    return exp.build_exposure_slice(
        agent_id,
        destination=destination,
        preset=preset,
        fields=fields,
    )


@mcp.tool()
@_guarded("agent_seed_mirror")
def agent_seed_mirror(app_id: str, agent_id: str, slice: str = "") -> dict:
    """Mirror a ratified home seed into SOIL collection willow_agents_seeds (AS-5).

    Requires ratified status; when WILLOW_PGP_FINGERPRINT is set the detached
    .sig must verify. slice: full | voice_only | work_context (omit for exposure.json default).
    """
    from . import gate
    from . import seed_mirror as sm

    if not gate.collection_permitted(app_id, sm.MIRROR_COLLECTION):
        return _collection_denied(app_id, sm.MIRROR_COLLECTION)
    return sm.mirror_seed_to_store(_store, agent_id, slice_name=slice)


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
    """Fleet health — task queue counts by status, plus live worker heartbeats.

    A queue depth is only half the picture: `pending` tasks with no live worker
    are not "queued", they are stranded. `workers` reports every process
    publishing a heartbeat, and `stranded` is true when there is pending work and
    nothing running to drain it."""
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
    from .heartbeat import read_workers
    workers = read_workers()
    pending = counts.get("pending", 0)
    return {
        "pending":   pending,
        "running":   counts.get("running", 0),
        "completed": counts.get("completed", 0),
        "failed":    counts.get("failed", 0),
        "total":     sum(counts.values()),
        "workers":   workers,
        "stranded":  pending > 0 and workers.get("alive", 0) == 0,
    }


# ── Session context tools ────────────────────────────────────────────────────
#
# Ephemeral, per-identity working state that survives across sessions — a
# to-do note, a cursor, a scratch value — with an optional TTL. Distinct from
# store_* in exactly that: contexts can expire, and reads transparently skip
# (and lazily purge) expired entries. Backed by the SOIL store, so this works
# with no Postgres — matching the README's "SOIL store works standalone."
# Scoped to the caller's app_id (the bound identity in serve mode), so one
# identity never reads another's context.

def _ctx_collection(app_id: str) -> str:
    return f"ctx__{app_id}"


def _ctx_expired(rec: dict) -> bool:
    exp = rec.get("_ctx_expires_epoch")
    return bool(exp) and time.time() > exp


@mcp.tool()
@_guarded("context_save")
def context_save(app_id: str, key: str, value: dict, ttl_seconds: int = 0) -> dict:
    """Save ephemeral working state under `key`, optionally expiring after
    ttl_seconds (0 = never). Overwrites an existing key. Per-identity — scoped
    to your app_id. Backed by the SOIL store, so no Postgres is required."""
    expires_epoch = (time.time() + ttl_seconds) if ttl_seconds and ttl_seconds > 0 else None
    expires_at = (datetime.fromtimestamp(expires_epoch, timezone.utc).isoformat()
                  if expires_epoch else None)
    record = {
        "value": value,
        "_ctx_key": key,
        "_ctx_saved_at": datetime.now(timezone.utc).isoformat(),
        "_ctx_expires_epoch": expires_epoch,
        "_ctx_expires_at": expires_at,
    }
    _store.put(_ctx_collection(app_id), record, record_id=key)
    return {"key": key, "expires_at": expires_at}


@mcp.tool()
@_guarded("context_get")
def context_get(app_id: str, key: str) -> dict:
    """Read a saved context by key. Returns {error: not_found} if absent, or
    {error: expired} (and purges it) if its TTL has passed."""
    coll = _ctx_collection(app_id)
    rec = _store.get(coll, key)
    if not rec:
        return {"error": "not_found"}
    if _ctx_expired(rec):
        _store.delete(coll, key)
        return {"error": "expired"}
    return {"key": key, "value": rec.get("value"),
            "saved_at": rec.get("_ctx_saved_at"),
            "expires_at": rec.get("_ctx_expires_at")}


@mcp.tool()
@_guarded("context_list")
def context_list(app_id: str) -> dict:
    """List your saved context keys with save/expiry times (values omitted —
    use context_get). Expired entries are skipped and purged."""
    coll = _ctx_collection(app_id)
    out = []
    for rec in _store.all(coll):
        key = rec.get("_ctx_key") or rec.get("_id")
        if _ctx_expired(rec):
            _store.delete(coll, key)
            continue
        out.append({"key": key, "saved_at": rec.get("_ctx_saved_at"),
                    "expires_at": rec.get("_ctx_expires_at")})
    return {"contexts": out}


@mcp.tool()
@_guarded("context_expire")
def context_expire(app_id: str, key: str) -> dict:
    """Delete a saved context now, before its TTL. Returns {expired: bool}."""
    return {"expired": _store.delete(_ctx_collection(app_id), key)}


# ── Integrations (outbound adapters) ─────────────────────────────────────────
#
# External HTTP APIs, called from the server process — see integrations.py for
# the adapter ledger (live vs declared stubs) and the earn rule. Live calls are
# the fourth consumer of the three-key egress gate: the integration_net
# capability (own line, never implied by task_net), the operator's standing
# consent.internet, and an unexpired lease. integration_call is additionally
# kept out of full_access (gate.py), so even the attempt surface is opt-in.

@mcp.tool()
@_guarded("integration_list")
def integration_list(app_id: str) -> dict:
    """List every integration adapter — live and declared stubs — with status,
    credential *source* (env/vault, never the value), and, for stubs, what is
    missing and what earns the implementation."""
    from . import integrations
    return {"integrations": integrations.list_integrations()}


@mcp.tool()
@_guarded("integration_status")
def integration_status(app_id: str, name: str) -> dict:
    """Offline readiness readout for one integration: live or stub, credential
    presence, and whether the three-key egress gate would pass for this app
    right now. Makes no network call — ask this before asking for a lease."""
    from . import integrations
    return integrations.status(app_id, name)


@mcp.tool()
@_guarded("integration_call")
def integration_call(app_id: str, name: str, method: str, path: str,
                     params: Optional[dict] = None,
                     body: Optional[dict] = None) -> dict:
    """Call an external API through a registered integration adapter.

    Egress needs THREE keys, all held at once: the 'integration_net' capability
    in this app's manifest (own line — NOT granted by task_net, integration_call,
    or full_access), the operator's standing consent.internet, and an unexpired
    egress lease issued via `willow-mcp grant-net`. Declared stubs refuse with
    what is missing and what earns their implementation."""
    from . import integrations
    adapter = integrations.get(name)
    if adapter is None:
        return {"error": f"unknown_integration: {name!r}",
                "known": sorted(integrations.REGISTRY)}
    denial = integrations.egress_denial(app_id)
    if denial:
        return denial
    return adapter.request(method, path, params=params, body=body)


# ── Self-audit ───────────────────────────────────────────────────────────────

@mcp.tool()
@_guarded("receipts_tail")
def receipts_tail(app_id: str, limit: int = 20) -> dict:
    """Return your own most-recent tool-call receipts, newest first: ts, tool,
    outcome (ok/denied/rate_limited/error), detail. Scoped to your app_id — a
    self-audit trail, never another identity's calls."""
    return {"receipts": _receipt_log.tail(app_id, limit)}


# ── Self-diagnostic ──────────────────────────────────────────────────────────
#
# "Is this willow-mcp install wired correctly?" — the one tool a user reaches
# for when nothing else works, so it must run even when the manifest is missing
# or the database is empty. It is therefore NOT wrapped in _guarded (a broken
# manifest would make the diagnostic itself undiagnosable). It reveals only the
# caller's own environment/config — no fleet rows, no vault secrets. In serve
# mode it still requires a confirmed identity, so an unbound remote caller never
# reads local internals; local filesystem paths are collapsed to ~ for a remote
# (bound) caller.
#
# Its headline job is catching the empty-DB / wrong-env failure: Postgres
# connects fine, but WILLOW_PG_DB points at a database without willow-mcp's
# tables (e.g. serve mode under systemd --user not inheriting a shell export).

_EXPECTED_PG_TABLES = {
    "knowledge":         "knowledge_* / kb_*",
    "tasks":             "task_* / fleet_health",
    "agents":            "fleet_status",
    "routing_decisions": "agent_route / agent_dispatch_result",
}


def _diag_store() -> dict:
    check: dict = {"backend": "soil-sqlite", "root": None, "exists": False,
                   "writable": False, "collections": 0, "names": []}
    try:
        root = _store.root
        check["root"] = str(root)
        check["exists"] = root.exists()
        try:
            root.mkdir(parents=True, exist_ok=True)
            probe = root / ".diag_write_probe"
            probe.write_text("ok")
            probe.unlink()
            check["writable"] = True
        except Exception as e:
            check["write_error"] = str(e)[:120]
        names = sorted(p.parent.name for p in root.glob("*/store.db")) if root.exists() else []
        check["collections"] = len(names)
        check["names"] = names[:20]
        check["status"] = "ok" if check["writable"] else "fail"
    except Exception as e:
        check["status"] = "fail"
        check["error"] = str(e)[:160]
    return check


def _diag_rings() -> dict:
    """Learned-mapping tree (schema_rings): how much column->field vocabulary this
    deployment has confirmed, and how close it sits to the prune (canopy) cap."""
    check: dict = {"backend": "schema-rings"}
    try:
        g = sp.girth()  # {columns, pairs, cap, tick}
        pairs = g.get("pairs", 0)
        cap = g.get("cap", 0) or 1
        check.update({
            "columns": g.get("columns", 0),
            "pairs": pairs,
            "cap": g.get("cap", 0),
            "confirmations": g.get("tick", 0),
            "saturation_pct": round(100.0 * pairs / cap, 1),
            "status": "ok",
        })
    except Exception as e:
        check["status"] = "fail"
        check["error"] = str(e)[:160]
    return check


def _diag_postgres() -> dict:
    check: dict = {"backend": "postgres", "reachable": False,
                   "dbname": os.environ.get("WILLOW_PG_DB", "willow"),
                   "user": os.environ.get("WILLOW_PG_USER", os.environ.get("USER", "")),
                   "tables": {}}
    pg = get_pg()
    if not pg:
        check["status"] = "fail"
        check["detail"] = "postgres_unavailable — not reachable via unix socket (knowledge_*, task_*, fleet_* degrade)"
        return check
    check["reachable"] = True
    try:
        dsn = pg.get_dsn_parameters()
        check["dbname"] = dsn.get("dbname", check["dbname"])
        check["host"] = dsn.get("host") or "local-socket"
        wanted = list(_EXPECTED_PG_TABLES)
        cur = pg.cursor()
        cur.execute(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name = ANY(%s)", (wanted,))
        present = {r[0] for r in cur.fetchall()}
        est: dict = {}
        if present:
            cur.execute("SELECT relname, reltuples::bigint FROM pg_class WHERE relname = ANY(%s)",
                        (list(present),))
            est = {r[0]: int(r[1]) for r in cur.fetchall()}
        cur.close()
        for t in wanted:
            check["tables"][t] = {"present": t in present, "rows_est": est.get(t),
                                   "backs": _EXPECTED_PG_TABLES[t]}
        check["missing"] = [t for t in wanted if t not in present]
        check["status"] = "ok" if not check["missing"] else "warn"
    except Exception as e:
        check["status"] = "fail"
        check["error"] = str(e)[:160]
    return check


def _diag_schema(app_id: str) -> dict:
    check: dict = {"tables": {}}
    pg = get_pg()
    if not pg:
        check["status"] = "skip"
        check["detail"] = "postgres unavailable"
        return check
    try:
        eff = app_id or "willow-mcp"
        for table, fields in _CONFIRMABLE_TABLES.items():
            m = sp.resolve(pg, eff, table, fields)
            if "error" in m:
                check["tables"][table] = {"present": False, "confirmed": False, "note": m["error"]}
                continue
            check["tables"][table] = {
                "present": True,
                "confirmed": bool(m.get("confirmed")),
                # field -> real column (names only, no row data) so a
                # confirmed-but-wrong mapping like content->content is visible
                # here; run schema_confirm_mapping(preview=True) to see the
                # rendered values that prove or disprove it.
                "columns": {f: v["column"] for f, v in m["fields"].items()},
                "unmapped": [f for f, v in m["fields"].items() if v["column"] is None],
                "drift": bool(m.get("schema_drift")),
            }
        check["status"] = "ok"
    except Exception as e:
        check["status"] = "fail"
        check["error"] = str(e)[:160]
    return check


def _diag_manifest(app_id: str) -> dict:
    from . import gate
    check: dict = {"app_id": app_id, "apps_root": str(gate._apps_root())}
    if not app_id:
        check["status"] = "warn"
        check["reason"] = "no_app_id"
        check["detail"] = "no app_id supplied — pass the app_id you call willow-mcp with"
        return check
    manifest = gate._load_manifest(app_id)
    if manifest is None:
        check["status"] = "fail"
        check["detail"] = f"no manifest at {gate._apps_root()}/{app_id}/manifest.json — every call is denied"
        return check
    perms = manifest.get("permissions", [])
    allowed: set = set()
    for p in perms:
        g = gate.PERMISSION_GROUPS.get(p)
        allowed.update(g if g is not None else {p})
    check["permissions"] = perms
    check["tools_allowed"] = sorted(allowed)
    if not perms:
        check["status"] = "warn"
        check["detail"] = "manifest present but permissions empty — every call is denied"
    else:
        check["status"] = "ok"
    return check


def _diag_bindings() -> dict:
    from . import gate
    root = gate._apps_root() / "_identity_bindings"
    check: dict = {"dir": str(root), "total": 0, "confirmed": 0}
    try:
        if root.exists():
            files = list(root.glob("*.json"))
            check["total"] = len(files)
            for f in files:
                try:
                    if json.loads(f.read_text()).get("confirmed"):
                        check["confirmed"] += 1
                except Exception:
                    pass
        check["status"] = "ok"
    except Exception as e:
        check["status"] = "fail"
        check["error"] = str(e)[:160]
    return check


def _diag_worker(app_id: str) -> dict:
    """Worker liveness + the queue depth that makes its absence matter.

    `pending` is best-effort: no Postgres, an unconfirmed mapping, or any query
    failure leaves it None, which means "unknown" and never raises a problem. An
    install that only uses store_*/knowledge_* has no worker and no queue — that
    is healthy, not degraded (B-18's lesson: don't diagnose a non-defect)."""
    from .heartbeat import read_workers
    check = read_workers()
    check["pending"] = None
    try:
        pg = get_pg()
        if pg is not None:
            mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
            status_col = mapping.get("fields", {}).get("status", {}).get("column")
            if "error" not in mapping and status_col:
                cur = pg.cursor()
                cur.execute(f'SELECT COUNT(*) FROM tasks WHERE "{status_col}" = %s', ("pending",))
                check["pending"] = cur.fetchone()[0]
                cur.close()
    except Exception:
        pass  # unknown, not broken
    return check


def _diag_consent() -> dict:
    """Standing operator consent — the fleet-wide key of the three-key egress gate.

    Read-only and fail-closed: willow-mcp never authors this policy, and anything
    it cannot read as an explicit `true` reads as denial."""
    from . import consent
    return consent.read_consent()


def _diag_net_lease(app_id: str) -> dict:
    """Egress leases — the third key, and an honest report on who could forge it.

    `self_writable` is the part that matters. It lists the trust-root paths this
    very process can write: every one of them is a key it could mint for itself.
    On a single-uid host that is all of them, which is exactly B-32."""
    from . import gate, lease
    holds_capability = bool(app_id) and gate.permitted(app_id, gate.NET_PERMISSION)
    forgeable = lease.self_writable_trust_paths(app_id)
    return {
        "lease_root": str(lease._leases_root()),
        "max_ttl_seconds": lease.MAX_TTL_SECONDS,
        "strict_trust_root": lease.strict_trust_root(),
        "holds_task_net": holds_capability,
        "lease": lease.read_lease(app_id) if app_id else {"status": "none"},
        "self_writable": forgeable,
        # A sub-check that lists the keys this process could forge and then calls
        # itself "ok" is asserting a membrane it just measured a hole in. The
        # verdict still turns on _derive_problems (a lone `warn` here would make
        # `degraded` every install's resting state, B-18) — but this field now
        # says what it found.
        "status": "ok" if not forgeable else "warn",
    }


def _under(child: Path, parent: Path) -> bool:
    """Is `child` the same inode as `parent`, or inside it — after symlinks?

    Compares resolved paths. `~/.willow` is commonly a symlink into a fleet tree,
    so a string prefix test reports "severed" for two names of one directory."""
    try:
        c, p = child.resolve(), parent.resolve()
    except OSError:
        return False
    return c == p or p in c.parents


def _diag_severance(store: dict, postgres: dict, net_lease: dict | None) -> dict:
    """Can this install still see the fleet it claims to be cut off from?

    Three properties, each independently checkable from inside the process:

      store      — the SOIL store is not the fleet's store
      postgres   — the database is not the fleet's database
      trust_root — this process cannot rewrite the ACLs that gate it

    The first two are DATA: someone who writes them corrupts records. The third
    is AUTHORITY: someone who writes it grants themselves egress. Only the third
    can turn a severed install into a compromised one, so only it is an `error`.

    Reports `not_asserted` when the operator has named no fleet. That is not a
    failure — a single-trust-domain install is complete without severance, and
    an install that has never claimed to be cut off cannot be caught lying."""
    fleet_home = paths.fleet_home()
    fleet_db = paths.fleet_pg_db()

    if fleet_home is None and not fleet_db:
        return {"status": "not_asserted",
                "detail": ("no fleet named — set WILLOW_MCP_FLEET_HOME and "
                           "WILLOW_MCP_FLEET_PG_DB to assert this install is severed from one"),
                "surfaces": {}}

    surfaces: dict = {}

    # ── data: store ───────────────────────────────────────────────────────────
    store_root = store.get("root")
    if fleet_home is None:
        surfaces["store"] = {"severed": None, "reason": "WILLOW_MCP_FLEET_HOME unset"}
    elif not store_root:
        surfaces["store"] = {"severed": None, "reason": "store root unresolved"}
    else:
        shared = _under(Path(store_root), fleet_home)
        surfaces["store"] = {
            "path": store_root, "severed": not shared,
            "reason": f"resolves inside {fleet_home}" if shared else None}

    # ── data: postgres ────────────────────────────────────────────────────────
    dbname = postgres.get("dbname")
    if not fleet_db:
        surfaces["postgres"] = {"severed": None, "reason": "WILLOW_MCP_FLEET_PG_DB unset"}
    else:
        shared = bool(dbname) and dbname == fleet_db
        surfaces["postgres"] = {
            "dbname": dbname, "severed": not shared,
            "reason": f"is the fleet database '{fleet_db}'" if shared else None}

    # ── authority: trust root ─────────────────────────────────────────────────
    # Reuses the paths _diag_net_lease already computes. A trust root this
    # process can write is a gate it can open, whether or not it holds task_net
    # today — B-32 (host self-grant) and B-33 (sandbox writes consent) are both
    # this property, observed at two different callers.
    forgeable = (net_lease or {}).get("self_writable") or []
    apps_root = paths.mcp_apps_root()
    inside_fleet = fleet_home is not None and _under(apps_root, fleet_home)
    surfaces["trust_root"] = {
        "apps_root": str(apps_root),
        "self_writable": [f["path"] for f in forgeable],
        "inside_fleet_home": inside_fleet,
        "severed": not forgeable and not inside_fleet,
    }

    violated = [k for k, v in surfaces.items() if v.get("severed") is False]
    unknown = [k for k, v in surfaces.items() if v.get("severed") is None]
    status = "violated" if violated else ("partial" if unknown else "ok")
    return {"status": status, "fleet_home": str(fleet_home) if fleet_home else None,
            "fleet_pg_db": fleet_db or None, "violated": violated,
            "unknown": unknown, "surfaces": surfaces}


def _diag_env() -> dict:
    # Config-bearing env, set-or-None. A var showing None here (its default in
    # effect) while data lives elsewhere is the serve-mode env footgun: the
    # systemd --user unit does not inherit a shell `export`.
    keys = ["WILLOW_HOME", "WILLOW_PG_DB", "WILLOW_PG_USER", "WILLOW_STORE_ROOT",
            "WILLOW_APP_ID", "WILLOW_MCP_APPS_ROOT", "WILLOW_MCP_HOST", "WILLOW_MCP_PORT",
            "WILLOW_SETTINGS_GLOBAL", "WILLOW_MCP_FLEET_HOME", "WILLOW_MCP_FLEET_PG_DB"]
    return {k: os.environ.get(k) for k in keys}


def _derive_problems(store: dict, postgres: dict, manifest: dict, mode: str,
                     worker: dict | None = None, consent: dict | None = None,
                     net_lease: dict | None = None, severance: dict | None = None) -> list[dict]:
    """Pure: turn raw check dicts into actionable problems. Unit-tested without
    a live DB — this is where the empty-DB footgun becomes a named diagnosis."""
    problems: list[dict] = []
    if store.get("status") == "fail":
        problems.append({"severity": "error", "check": "store",
                         "detail": store.get("write_error") or store.get("error") or "SOIL store not writable",
                         "fix": f"ensure {store.get('root')} exists and is writable (WILLOW_STORE_ROOT)"})
    if postgres.get("status") == "fail":
        problems.append({"severity": "warn", "check": "postgres",
                         "detail": "Postgres unreachable — knowledge_*, task_*, fleet_* will return postgres_unavailable",
                         "fix": "start Postgres and confirm unix-socket peer auth for WILLOW_PG_USER, or ignore if you only use the SOIL store"})
    elif postgres.get("missing"):
        env_note = (" Serve mode (systemd --user) does not inherit a shell `export WILLOW_PG_DB` — "
                    "see README 'Turning serve mode on and off'.") if mode == "serve" else ""
        problems.append({"severity": "error", "check": "postgres",
                         "detail": (f"Postgres connected to database '{postgres.get('dbname')}' but "
                                    f"expected tables are missing: {postgres['missing']}. "
                                    f"If your data lives in another database, WILLOW_PG_DB is wrong." + env_note),
                         "fix": f"set WILLOW_PG_DB to the database that actually holds these tables (currently '{postgres.get('dbname')}')"})
    if manifest.get("status") == "fail":
        problems.append({"severity": "error", "check": "manifest",
                         "detail": manifest.get("detail"),
                         "fix": f"create/populate {manifest.get('apps_root')}/{manifest.get('app_id')}/manifest.json with a \"permissions\" list"})
    elif manifest.get("status") == "warn":
        p = {"severity": "warn", "check": "manifest", "detail": manifest.get("detail")}
        if manifest.get("reason") == "no_app_id":
            # Caller omission, not an install defect: the caller didn't pass an
            # app_id to this self-check. Surfaced here (and in checks.manifest)
            # but flagged caller_input so it does NOT drag the verdict off "ok"
            # when every probed subsystem is healthy (B-18).
            p["caller_input"] = True
            p["fix"] = "pass app_id=<the id you call willow-mcp with> to diagnostic_summary"
        else:
            p["fix"] = (f"populate {manifest.get('apps_root')}/{manifest.get('app_id')}"
                        "/manifest.json with a non-empty \"permissions\" list")
        problems.append(p)
    if worker:
        pending = worker.get("pending")
        alive = worker.get("alive", 0)
        # No worker is only a defect when something is waiting on one. An install
        # that never submits tasks is complete without a worker; saying otherwise
        # would make `degraded` the resting state for most installs.
        if alive == 0 and isinstance(pending, int) and pending > 0:
            died = [w for w in worker.get("workers", []) if w.get("state") in ("stale", "dead")]
            detail = (f"{pending} task(s) pending and no live worker — nothing will drain the "
                      f"queue; task_submit will return task_ids that never execute")
            if died:
                detail += (f" (found {len(died)} heartbeat(s) from stopped worker(s): "
                           f"{', '.join(str(w.get('pid')) for w in died)})")
            problems.append({"severity": "warn", "check": "worker", "detail": detail,
                             "fix": "start a worker: `willow-mcp worker --lane fast` "
                                    "(or `--once` to drain and exit)"})
    if consent:
        if consent.get("status") == "fail":
            problems.append({
                "severity": "error", "check": "consent",
                "detail": (f"consent policy at {consent.get('canonical_path')} is "
                           f"{consent.get('error')} — every consent key is denied, so "
                           "allow_net tasks will be refused"),
                "fix": f"repair or remove {consent.get('canonical_path')}"})
        disagreement = consent.get("disagreement")
        if disagreement:
            # Never resolved silently: the two files are both plausible statements
            # of operator intent, and picking one is the operator's call. The
            # canonical file is what willow-mcp obeys; say so, and say what the
            # other one claims, so a stale `internet: false` cannot look like a
            # setting that is doing something.
            #
            # Do NOT advise deleting consent.json (B-30). It is a mirror, not a
            # leftover: willow-2.0's save_global_settings(sync_legacy=True) — the
            # default — recreates it from the canonical block on every save, as does
            # Grove's consent toggle. A delete looks like a fix and comes back.
            keys = ", ".join(disagreement["keys"])
            problems.append({
                "severity": "error", "check": "consent",
                "detail": (f"consent disagrees between files on: {keys}. "
                           f"canonical={disagreement['canonical']} "
                           f"legacy={disagreement['legacy']}. willow-mcp obeys the "
                           f"canonical file. {consent.get('legacy_path')} is a mirror "
                           f"willow-2.0 rewrites on every save and reads only when the "
                           f"canonical file is absent — so it is a stale mirror, not an "
                           f"inert file, and deleting it will not keep it gone."),
                "fix": ("decide which value states your intent. To keep the canonical "
                        "one, re-sync the mirror: `python -c \"from "
                        "willow.fylgja.global_settings import read_consent, "
                        "_write_legacy_consent as w; w(read_consent())\"`. To change "
                        f"policy, edit {consent.get('canonical_path')} — the mirror "
                        "follows on the next save.")})
    if net_lease:
        lease_state = net_lease.get("lease", {})
        status = lease_state.get("status")
        if status in ("malformed", "mismatch"):
            # Denies egress either way (fail-closed), so the install is not broken —
            # but a lease file that does not parse, or one whose record names a
            # different app than the file it sits in, is a hand-edit or a forgery
            # attempt. Neither should pass silently.
            problems.append({
                "severity": "warn", "check": "net_lease",
                "detail": (f"egress lease at {lease_state.get('path')} is {status}"
                           + (f": {lease_state['error']}" if lease_state.get("error") else "")
                           + " — allow_net is denied. A lease is only ever written by "
                             "`willow-mcp grant-net`; this one was not, or was edited after."),
                "fix": f"remove it, then re-issue with `willow-mcp grant-net {net_lease.get('app_id') or lease_state.get('app_id') or '<app_id>'} --ttl 30m`"})
        forgeable = net_lease.get("self_writable") or []
        if forgeable and net_lease.get("strict_trust_root"):
            problems.append({
                "severity": "error", "check": "net_lease",
                "detail": ("WILLOW_MCP_STRICT_TRUST_ROOT is set, but this process can write "
                           "the keys that authorize it: "
                           + ", ".join(f["path"] for f in forgeable)
                           + " — every allow_net task will be refused"),
                "fix": "chown the lease root and manifest to a uid the agent does not run as, "
                       "or unset WILLOW_MCP_STRICT_TRUST_ROOT and accept the residual (B-32)"})
        elif forgeable and net_lease.get("holds_task_net"):
            # Only for an app that actually holds the egress capability. Warning on
            # every install would make `degraded` the resting verdict for the many
            # that never request egress — the false-positive class B-18 removed.
            problems.append({
                "severity": "warn", "check": "net_lease",
                "detail": ("this app holds 'task_net' and this process can write the keys "
                           "that authorize its egress: "
                           + ", ".join(f"{f['key']} ({f['path']})" for f in forgeable)
                           + ". Leases expire and are attributed, so a self-grant now decays "
                             "and leaves a record — but the OS is not preventing one. "
                             "Request and confirm are not yet separate authorities here (B-32)."),
                "fix": "chown the lease root (and manifest) to a uid the agent does not run as, "
                       "then set WILLOW_MCP_STRICT_TRUST_ROOT=1 to enforce it"})
    if severance and severance.get("status") not in (None, "not_asserted"):
        surfaces = severance.get("surfaces", {})
        # A severed install that reports `ok` while wired to the fleet is worse
        # than no check at all. Once the operator has named a fleet, every surface
        # that still resolves into it is a named problem.
        for name in severance.get("violated", []):
            surf = surfaces.get(name, {})
            if name == "trust_root":
                # AUTHORITY, not data. This process can rewrite the ACLs that gate
                # it: the manifest that grants task_net, the lease root, the consent
                # file. Severance from a fleet whose gate you still hold the pen for
                # is not severance. B-32 (host lane) and B-33 (sandbox lane).
                writable = ", ".join(surf.get("self_writable", [])) or surf.get("apps_root", "")
                problems.append({
                    "severity": "error", "check": "severance",
                    "detail": ("this install claims severance but its trust root is within "
                               "reach: " + writable + ". A process that can write its own "
                               "manifest, lease root, or consent file can grant itself the "
                               "egress the cut was supposed to deny."),
                    "fix": ("move the trust root outside every path this process and the Kart "
                            "sandbox can write (WILLOW_MCP_APPS_ROOT), and chown it to a uid "
                            "the agent does not run as")})
            else:
                # DATA. Corruptible, not authority-bearing. Degrades; does not break.
                problems.append({
                    "severity": "warn", "check": "severance",
                    "detail": (f"{name} is not severed from the fleet named by "
                               f"WILLOW_MCP_FLEET_HOME/WILLOW_MCP_FLEET_PG_DB: "
                               f"{surf.get('reason')}"),
                    "fix": (f"point WILLOW_STORE_ROOT at a store outside "
                            f"{severance.get('fleet_home')}" if name == "store"
                            else f"set WILLOW_PG_DB to a database other than "
                                 f"'{severance.get('fleet_pg_db')}'")})
        for name in severance.get("unknown", []):
            # Half a claim. The operator asserted severance from *something* but
            # left the other coordinate unnamed, so this surface cannot be checked
            # either way. Fail closed: an unverifiable claim is not a passing one.
            problems.append({
                "severity": "warn", "check": "severance",
                "detail": (f"severance is asserted but {name} cannot be checked: "
                           f"{surfaces.get(name, {}).get('reason')}"),
                "fix": "set both WILLOW_MCP_FLEET_HOME and WILLOW_MCP_FLEET_PG_DB, or neither"})
    return problems


def _derive_verdict(problems: list[dict]) -> str:
    if any(p["severity"] == "error" for p in problems):
        return "broken"
    # caller_input problems (e.g. no app_id passed to this self-check) are warns
    # that describe the CALL, not the install — they surface in `problems` and
    # the relevant sub-check, but must not drag the verdict off "ok" when every
    # probed subsystem is healthy (B-18).
    if any(not p.get("caller_input") for p in problems):
        return "degraded"
    return "ok"


def _collapse_home(obj):
    """Replace the home-dir prefix with ~ in any string values (serve-mode
    redaction for a remote bound caller — no absolute host paths leak)."""
    home = str(os.path.expanduser("~"))
    if isinstance(obj, str):
        return obj.replace(home, "~")
    if isinstance(obj, dict):
        return {k: _collapse_home(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_collapse_home(v) for v in obj]
    return obj


@mcp.tool()
def diagnostic_summary(app_id: str = "") -> dict:
    """Self-check: is this willow-mcp install wired correctly? Reports the SOIL
    store (path/writable/collections), Postgres (reachable + which database +
    whether willow-mcp's tables are present), schema-mapping confirmation state,
    your app_id's manifest + resolved permissions, identity bindings, whether a
    task worker is alive to drain the queue, your egress lease and which of the
    keys authorizing it this process could forge, whether this install is still
    wired to a fleet it claims to be severed from, and the config-bearing
    environment — then a verdict (ok/degraded/broken) with named problems and
    fixes. Ungated on purpose: it must answer even when your manifest or database
    is misconfigured. Reveals only your own config, never fleet rows or vault secrets.

    Severance is asserted, never assumed: name a fleet with WILLOW_MCP_FLEET_HOME
    and WILLOW_MCP_FLEET_PG_DB and every shared surface becomes a named problem.
    Name none and the check reports `not_asserted` and changes nothing."""
    mode = "serve" if _SERVE_MODE else "stdio"
    redact = False
    if _SERVE_MODE:
        bound, err = _resolve_serve_identity()
        if err:
            return {"verdict": "unauthenticated", "mode": mode, "detail": err["error"],
                    "hint": "sign in and have the operator confirm your binding, then call diagnostic_summary again"}
        app_id = bound
        redact = True
        allowed, retry_after = _check_rate(app_id)
        if not allowed:
            return {"error": "rate_limited", "retry_after": retry_after}

    eff = app_id or _DEFAULT_APP_ID
    store = _diag_store()
    postgres = _diag_postgres()
    rings = _diag_rings()
    schema = _diag_schema(eff)
    manifest = _diag_manifest(eff)
    bindings = _diag_bindings()
    worker = _diag_worker(eff)
    consent = _diag_consent()
    net_lease = _diag_net_lease(eff)
    severance = _diag_severance(store, postgres, net_lease)
    env = _diag_env()

    problems = _derive_problems(store, postgres, manifest, mode, worker, consent,
                                net_lease, severance)
    verdict = _derive_verdict(problems)

    report = {
        "verdict": verdict,
        "mode": mode,
        "serve": {"host": _HOST, "port": _PORT, "base_url": _BASE_URL} if _SERVE_MODE else None,
        "app_id": eff or None,
        "checks": {"store": store, "postgres": postgres, "rings": rings,
                   "schema": schema, "manifest": manifest, "identity_bindings": bindings,
                   "worker": worker, "consent": consent, "net_lease": net_lease,
                   "severance": severance, "env": env},
        "problems": problems,
    }
    if redact:
        report = _collapse_home(report)
    try:
        _receipt_log.record(eff or "-", "diagnostic_summary", "ok" if verdict == "ok" else "warn", verdict)
    except Exception:
        pass
    return report


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


def _cmd_worker(args) -> None:
    """Drain the Kart queue via the kartikeya worker (CLI: `willow-mcp worker`)."""
    try:
        import kartikeya
    except ModuleNotFoundError:
        print(
            "willow-mcp worker requires the 'kartikeya' package, which willow-mcp "
            "depends on — reinstall with `pip install willow-mcp`, or "
            "`pip install -e .` from a source checkout.",
            file=sys.stderr,
        )
        raise SystemExit(1)
    from .task_queue import build_task_queue

    try:
        queue = build_task_queue(args.app_id or _DEFAULT_APP_ID)
    except RuntimeError as e:
        print(f"willow-mcp worker: {e}", file=sys.stderr)
        raise SystemExit(1)

    from .heartbeat import WorkerHeartbeat, reap
    reap()  # clear files left by workers that were killed rather than stopped
    beat = WorkerHeartbeat(agent="kart", lane=args.lane, interval=args.interval)
    try:
        kartikeya.run_worker(
            queue, lane=args.lane, slots=args.slots, interval=args.interval,
            once=args.once, on_heartbeat=beat,
        )
    finally:
        beat.close()


def _cmd_grant_net(args) -> None:
    """`willow-mcp grant-net` — issue a time-boxed egress lease (B-32).

    Local/stdio-only by design, exactly like `confirm-binding`: no MCP tool can
    reach this, so an agent can request egress and never grant it to itself. The
    lease expires on its own; the ceiling is 3h (FRANK `cc553729`).
    """
    from . import lease

    try:
        ttl = lease.parse_ttl(args.ttl)
        record = lease.grant(args.app_id, ttl, issuer=args.issuer, reason=args.reason or "")
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Egress lease issued to app_id={record['app_id']!r} by {record['issuer']!r}\n"
          f"  expires: {record['expires_at']} (ttl {record['ttl_seconds']}s)\n"
          f"  reason:  {record['reason'] or '(none given)'}")
    forgeable = lease.self_writable_trust_paths(args.app_id)
    if forgeable and not lease.strict_trust_root():
        print("\n  NOTE: this host has no uid separation — the agent's own process can write\n"
              "  " + ", ".join(f["path"] for f in forgeable) + "\n"
              "  so this lease constrains time and leaves a record, but does not prevent a\n"
              "  self-grant. See B-32.", file=sys.stderr)


def _cmd_revoke_net(args) -> None:
    """`willow-mcp revoke-net` — end an egress lease before it expires."""
    from . import lease

    try:
        had = lease.revoke(args.app_id)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    print(f"Egress lease for {args.app_id!r} {'revoked' if had else 'was not present'}.")


def _cmd_net_status(args) -> None:
    """`willow-mcp net-status` — what egress is currently authorized, and by whom."""
    from . import lease

    leases = [lease.read_lease(args.app_id)] if args.app_id else lease.list_leases()
    if not leases:
        print("No egress leases on disk. allow_net is denied for every app.")
    for st in leases:
        line = f"{st['app_id']:<24} {st['status']}"
        if st["status"] == "active":
            line += f"  expires in {st['remaining_seconds']}s (issuer: {st.get('issuer')})"
        elif st.get("error"):
            line += f"  — {st['error']}"
        print(line)
    forgeable = lease.self_writable_trust_paths(args.app_id or "")
    print(f"\nstrict_trust_root: {lease.strict_trust_root()}")
    if forgeable:
        print("self-writable trust paths (keys this process could forge):")
        for f in forgeable:
            print(f"  {f['key']}: {f['path']}")


def _cmd_gates(args) -> None:
    """`willow-mcp gates` — every authorization gate as one on/off panel."""
    from . import gates_panel

    rows = gates_panel.collect(args.app_id or "")

    if args.json:
        print(json.dumps([r.__dict__ for r in rows], indent=2))
        return

    if not args.no_tui or not args.html:
        print(gates_panel.render_tui(rows))

    if args.html:
        html = gates_panel.render_html(rows, datetime.now(timezone.utc).isoformat())
        out = Path(args.html).expanduser()
        out.write_text(html, encoding="utf-8")
        print(f"\nwrote {out}")


def _cmd_tree(args) -> None:
    """`willow-mcp tree` — every tree part in one call, for a real dashboard."""
    from . import tree_view

    eff_app_id = args.app_id or _DEFAULT_APP_ID
    tree = tree_view.build_tree(eff_app_id)
    if args.json:
        print(json.dumps(tree, indent=2, default=str))
    else:
        print(tree_view.render_summary(tree))


def _cmd_set_permission(args, *, granted: bool) -> None:
    """`willow-mcp allow-permission` / `deny-permission` — flip one manifest
    permission for one app. Local/stdio-only, exactly like `grant-net`: no
    MCP tool can reach this, so an agent can never grant itself a permission
    it was just denied.
    """
    from . import manifest_admin

    try:
        manifest = manifest_admin.set_permission(args.app_id, args.permission, granted)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        raise SystemExit(1)
    verb = "granted to" if granted else "revoked from"
    print(f"Permission {args.permission!r} {verb} app_id={args.app_id!r}.")
    print(f"  permissions now: {manifest['permissions']}")


def main():
    """Entry point. Wraps `_main` so a downstream reader closing early
    (`willow-mcp gates | head`, `... | grep -q`) exits clean instead of an
    unhandled `BrokenPipeError` traceback — several of these subcommands
    (`gates`, `net-status`, `tree`) print multiple lines and are exactly the
    shape someone pipes into `head`/`grep`."""
    try:
        _main()
    except BrokenPipeError:
        # Standard recipe (see Python docs, "brokenpipeerror-example"): the
        # reader is gone, so redirect our still-open stdout to devnull before
        # exiting — otherwise Python's own shutdown flush re-raises trying to
        # write to the closed pipe and prints a second, spurious traceback.
        devnull = os.open(os.devnull, os.O_WRONLY)
        os.dup2(devnull, sys.stdout.fileno())
        sys.exit(1)


def _main():
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

    worker_p = subparsers.add_parser(
        "worker",
        help="Run the Kart task worker (drains the queue; publishes a liveness heartbeat)",
    )
    worker_p.add_argument("--lane", default="fast", choices=["fast", "batch"])
    worker_p.add_argument("--slots", type=int, default=None)
    worker_p.add_argument("--interval", type=float, default=5.0)
    worker_p.add_argument("--once", action="store_true", help="drain the queue and exit")
    worker_p.add_argument("--app-id", dest="app_id", default=os.environ.get("WILLOW_APP_ID", ""),
                          help="app_id whose confirmed 'tasks' mapping to use (default $WILLOW_APP_ID)")

    grant_p = subparsers.add_parser(
        "grant-net",
        help="Issue a time-boxed egress lease for an app_id (local-only — never an MCP tool)",
    )
    grant_p.add_argument("app_id")
    grant_p.add_argument("--ttl", default="30m",
                         help="lease lifetime: 900s / 30m / 2h (ceiling 3h)")
    grant_p.add_argument("--reason", default="", help="why this grant exists — it is recorded")
    grant_p.add_argument("--issuer", default=os.environ.get("USER", "operator"),
                         help="who is issuing the lease (default $USER)")

    revoke_p = subparsers.add_parser("revoke-net", help="End an egress lease before it expires")
    revoke_p.add_argument("app_id")

    status_p = subparsers.add_parser(
        "net-status", help="Show egress leases and which trust-root keys this process can forge")
    status_p.add_argument("app_id", nargs="?", default="")

    gates_p = subparsers.add_parser(
        "gates",
        help="Show every authorization gate (consent, manifest permissions, egress "
             "lease, identity bindings, worker...) as one on/off panel, egress-lease shaped",
    )
    gates_p.add_argument("app_id", nargs="?", default="",
                          help="scope to one app_id (default: every app under mcp_apps/)")
    gates_p.add_argument("--html", nargs="?", const="willow-gates.html", default=None,
                          metavar="PATH",
                          help="write a static HTML snapshot instead of (or as well as) "
                               "the terminal table; defaults to ./willow-gates.html")
    gates_p.add_argument("--json", action="store_true", help="print raw JSON, no table")
    gates_p.add_argument("--no-tui", action="store_true",
                          help="with --html, skip printing the terminal table")

    allow_p = subparsers.add_parser(
        "allow-permission",
        help="Add a permission group (or the task_net capability) to an app's manifest")
    allow_p.add_argument("app_id")
    allow_p.add_argument("permission")

    deny_p = subparsers.add_parser(
        "deny-permission",
        help="Remove a permission group (or the task_net capability) from an app's manifest")
    deny_p.add_argument("app_id")
    deny_p.add_argument("permission")

    tree_p = subparsers.add_parser(
        "tree",
        help="Dump every tree part (trunk/sap/canopy/roots/rings/leaves/litter/stomata) "
             "as one call — the integration seam for a real dashboard",
    )
    tree_p.add_argument("app_id", nargs="?", default=os.environ.get("WILLOW_APP_ID", ""))
    tree_p.add_argument("--json", action="store_true", help="print raw JSON, no summary")

    compile_p = subparsers.add_parser(
        "compile-agents",
        help="Compile mcp_apps/*/manifest.json from specialists registry",
    )
    compile_p.add_argument(
        "--force",
        action="store_true",
        help="overwrite existing manifests (default: only missing)",
    )
    compile_p.add_argument("--dry-run", action="store_true", help="report paths only")
    compile_p.add_argument(
        "--registry",
        default="",
        help="path to specialists.json (default: $WILLOW_HOME/config or bundle)",
    )

    persona_p = subparsers.add_parser(
        "compile-persona",
        help="Compile personas/{agent_id}.md from $WILLOW_HOME/seeds/{agent_id}.json",
    )
    persona_p.add_argument("agent_id", help="agent id (e.g. hanuman, willow)")
    persona_p.add_argument("--force", action="store_true", help="overwrite existing persona .md")
    persona_p.add_argument("--dry-run", action="store_true", help="preview markdown without writing")
    persona_p.add_argument("--out", default="", help="optional output path")

    args, _ = parser.parse_known_args()

    if args.command == "setup":
        _cmd_setup(args)
        return
    if args.command == "confirm-binding":
        _cmd_confirm_binding(args)
        return
    if args.command == "worker":
        _cmd_worker(args)
        return
    if args.command == "grant-net":
        _cmd_grant_net(args)
        return
    if args.command == "revoke-net":
        _cmd_revoke_net(args)
        return
    if args.command == "net-status":
        _cmd_net_status(args)
        return
    if args.command == "gates":
        _cmd_gates(args)
        return
    if args.command == "allow-permission":
        _cmd_set_permission(args, granted=True)
        return
    if args.command == "deny-permission":
        _cmd_set_permission(args, granted=False)
        return
    if args.command == "tree":
        _cmd_tree(args)
        return
    if args.command == "compile-agents":
        from pathlib import Path

        from .registry import compile_agents_main

        reg = Path(args.registry).expanduser() if args.registry else None
        result = compile_agents_main(
            force=args.force,
            dry_run=args.dry_run,
            registry_file=reg,
        )
        print(json.dumps(result, indent=2))
        return
    if args.command == "compile-persona":
        from pathlib import Path

        from .persona_compile import compile_persona

        out = Path(args.out).expanduser() if args.out else None
        print(json.dumps(compile_persona(args.agent_id, dry_run=args.dry_run, force=args.force, out_path=out), indent=2))
        return

    if args.serve or _SERVE_MODE:
        mcp.run(transport="streamable-http")
    else:
        mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
