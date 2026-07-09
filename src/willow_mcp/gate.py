# willow_mcp/gate.py — manifest-based per-tool ACL gate.
#
# Identity model (stdio mode):
#   app_id is passed on every tool call. An app is authorized when a manifest
#   JSON file exists at $WILLOW_HOME/mcp_apps/<app_id>/manifest.json.
#   The manifest's "permissions" list controls which tools the app may call.
#
# Identity model (HTTP serve mode, Phase 2):
#   OAuth-verified identity (Google/Apple sub claim) is written into the
#   session before any tool dispatch; gate reads it from the session context.
#
# Fail-closed: missing app_id, missing manifest, or empty permissions → deny.
# No GPG required — file-system trust (single-operator assumption).
import json
import logging
import os
import re
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_APP_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _apps_root() -> Path:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))
    return Path(os.environ.get("WILLOW_MCP_APPS_ROOT", home / "mcp_apps"))


def _validate_app_id(app_id: str) -> str:
    if not app_id or not _APP_ID_RE.match(app_id):
        raise ValueError(f"Invalid app_id: {app_id!r}")
    return app_id


# Permission groups — named bundles that expand to sets of tool names.
# An app manifest lists group names and/or literal tool names in "permissions".
PERMISSION_GROUPS: dict[str, frozenset] = {
    "store_read": frozenset({
        "store_get", "store_search", "store_list", "store_search_all",
    }),
    "store_write": frozenset({
        "store_put", "store_update", "store_delete",
    }),
    "store_all": frozenset({
        "store_put", "store_get", "store_list", "store_update",
        "store_search", "store_delete", "store_search_all",
    }),
    "knowledge_read": frozenset({
        "knowledge_search",
        "kb_search", "kb_at", "kb_startup_continuity",
    }),
    "knowledge_write": frozenset({
        "knowledge_ingest",
        "kb_ingest", "kb_journal", "kb_promote",
    }),
    "task_queue": frozenset({
        "task_submit", "task_status", "task_list",
    }),
    "agent_dispatch": frozenset({
        "agent_route", "agent_dispatch_result",
    }),
    "dispatch_read": frozenset({
        "dispatch_read", "dispatch_list", "handoff_read", "session_read", "session_enter",
        "specialist_list", "specialist_get",
    }),
    "dispatch_write": frozenset({
        "dispatch_send", "dispatch_accept", "handoff_write_v4",
        "verify_handoff", "agent_clear", "session_handoff_write",
    }),
    "orchestrator": frozenset({
        "dispatch_send", "dispatch_read", "dispatch_list", "dispatch_accept",
        "handoff_write_v4", "handoff_read", "verify_handoff", "agent_clear",
        "session_read", "session_enter", "session_handoff_write", "agent_route", "agent_dispatch_result",
        "fleet_status", "fleet_health", "context_save", "context_get",
        "context_list", "knowledge_search", "store_get", "store_search",
        "specialist_list", "specialist_get",
    }),
    "fleet_read": frozenset({
        "fleet_status", "fleet_health",
    }),
    "context": frozenset({
        "context_save", "context_get", "context_list", "context_expire",
    }),
    "audit": frozenset({
        "receipts_tail",
    }),
    # Confirming a schema mapping unlocks write tools for a whole table — a
    # more consequential act than any single write, so it's gated as its
    # own group rather than folded into knowledge_write (docs/design/
    # schema-adaptation.md §8 open question, resolved this way).
    "schema_admin": frozenset({
        "schema_confirm_mapping",
    }),
    "full_access": frozenset({
        # Core store
        "store_put", "store_get", "store_list", "store_update",
        "store_search", "store_delete", "store_search_all",
        # Knowledge
        "knowledge_search", "knowledge_ingest",
        "kb_search", "kb_at", "kb_startup_continuity",
        "kb_ingest", "kb_journal", "kb_promote",
        # Tasks
        "task_submit", "task_status", "task_list",
        # Dispatch
        "agent_route", "agent_dispatch_result",
        "dispatch_send", "dispatch_read", "dispatch_list", "dispatch_accept",
        "handoff_write_v4", "handoff_read", "verify_handoff", "agent_clear",
        "session_read", "session_enter", "session_handoff_write",
        # Fleet (read-only)
        "fleet_status", "fleet_health",
        # Schema admin
        "schema_confirm_mapping",
        # Session context
        "context_save", "context_get", "context_list", "context_expire",
        # Self-audit
        "receipts_tail",
    }),
}


# Capability permissions — privilege flags a manifest may list to unlock an
# extra capability on a tool it already holds, rather than a tool name of their
# own. Checked explicitly by the tool (task_submit checks NET_PERMISSION before
# honoring allow_net). Deliberately NOT folded into full_access or task_queue:
# network egress from the Kart sandbox is an escalated privilege that must be
# granted on its own line, so a broad task_queue/full_access grant never
# silently carries net access with it (B-19; same spirit as B-14's trust-root
# separation).
NET_PERMISSION = "task_net"


def _load_manifest(app_id: str) -> Optional[dict]:
    root = _apps_root()
    manifest_path = root / app_id / "manifest.json"
    if not manifest_path.exists():
        return None
    try:
        return json.loads(manifest_path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("gate: manifest unreadable for %s: %s", app_id, e)
        return None


def authorized(app_id: str) -> bool:
    """Return True if a manifest exists for this app_id."""
    try:
        app_id = _validate_app_id(app_id)
    except ValueError:
        return False
    return _load_manifest(app_id) is not None


#: Returned when a scope cannot be established. `[]` denies every collection
#: (see db.collection_in_scope), so an unreadable policy confines rather than
#: releases. Distinct from None, which means "no policy declared".
_DENY_ALL: list = []


def store_scope(app_id: str) -> Optional[list]:
    """Return this app's manifest `store_scope` list.

    Three outcomes, and the difference between them is the whole point:

    * **Field absent, or explicitly `null` → `None` → unrestricted.** The store
      is deliberately shared with the wider Willow fleet via WILLOW_STORE_ROOT,
      so an app that never opted into isolation keeps seeing what it always saw.
      An explicit `null` is a declaration of no policy, not a broken one.
    * **Field present and well-formed → that list.** Exact names and/or
      `prefix*` wildcards; `[]` denies everything.
    * **Scope undeterminable → `[]` → deny-all.** A bad app_id, a missing or
      unreadable manifest, or a malformed `store_scope` cannot be read as
      consent. Returning None here would hand full store access to an operator
      who typed `"store_scope": "myapp_*"` (a string, the obvious typo for this
      field) and believes the app is confined. The app breaks loudly instead,
      which is the only outcome that reaches a human.

    This module fails closed on missing app_id, missing manifest, and empty
    permissions (see header). Scope now does too. See B-24 / L-ISO-01.
    """
    try:
        app_id = _validate_app_id(app_id)
    except ValueError:
        logger.warning("gate: invalid app_id %r for store_scope — denying all collections", app_id)
        return list(_DENY_ALL)
    manifest = _load_manifest(app_id)
    if manifest is None:
        logger.warning("gate: no readable manifest for %r — denying all collections", app_id)
        return list(_DENY_ALL)
    scope = manifest.get("store_scope")
    if scope is None:
        return None
    if not isinstance(scope, list) or not all(isinstance(p, str) for p in scope):
        logger.error(
            "gate: malformed store_scope for %r (expected a list of strings, got %r) "
            "— denying all collections",
            app_id,
            type(scope).__name__,
        )
        return list(_DENY_ALL)
    return scope


def collection_permitted(app_id: str, collection: str) -> bool:
    """True if this app's (optional) store_scope allows touching `collection`."""
    from . import db
    return db.collection_in_scope(collection, store_scope(app_id))


def permitted(app_id: str, tool_name: str) -> bool:
    """
    Return True if app_id is authorized and its manifest permits tool_name.

    Reads "permissions" from the manifest — a list of group names and/or
    literal tool names. Expands groups via PERMISSION_GROUPS.
    Fail-closed: empty or missing permissions → deny.
    """
    try:
        app_id = _validate_app_id(app_id)
    except ValueError:
        logger.warning("gate: invalid app_id %r rejected (tool=%r)", app_id, tool_name)
        return False

    manifest = _load_manifest(app_id)
    if manifest is None:
        logger.warning("gate: no manifest for %r (tool=%r) — denied", app_id, tool_name)
        return False

    perms: list = manifest.get("permissions", [])
    if not perms:
        logger.warning("gate: empty permissions for %r (tool=%r) — denied", app_id, tool_name)
        return False

    allowed: set = set()
    for perm in perms:
        group = PERMISSION_GROUPS.get(perm)
        if group is not None:
            allowed.update(group)
        else:
            allowed.add(perm)

    if tool_name not in allowed:
        logger.info("gate: %r denied tool %r (permissions=%r)", app_id, tool_name, perms)
        return False

    deny: list = manifest.get("deny_tools") or []
    if not isinstance(deny, list):
        logger.error("gate: malformed deny_tools for %r — denying %r", app_id, tool_name)
        return False
    if tool_name in deny:
        logger.info("gate: %r denied tool %r (deny_tools)", app_id, tool_name)
        return False

    return True
