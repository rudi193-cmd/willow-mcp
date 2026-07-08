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
    "fleet_read": frozenset({
        "fleet_status", "fleet_health",
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
        # Fleet (read-only)
        "fleet_status", "fleet_health",
    }),
}


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

    return True
