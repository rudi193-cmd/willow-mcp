"""willow_mcp/manifest_admin.py — local-CLI-only manifest permission toggles.

Companion to `lease.py`/`identity_binding.py`'s sudo invariant: an app's own
`manifest.json` is the file that grants it tool access, so writing it must
never be reachable from an MCP tool call — an agent could otherwise grant
itself whatever it was just denied. `set_permission()` backs the
`willow-mcp allow-permission` / `deny-permission` CLI subcommands
(stdio-only, operator-run), the same boundary as `grant-net` and
`confirm-binding`. **Do not wire this into an `@mcp.tool()`.**

This does not replace hand-editing `manifest.json` or regenerating it from
`specialists.json` via `willow-mcp compile-agents` — it just gives an
operator a one-line way to flip a single permission group without opening
an editor.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from .gate import (
    INTEGRATION_NET_PERMISSION,
    WEB_NET_PERMISSION,
    NET_PERMISSION,
    PERMISSION_GROUPS,
    _apps_root,
    _validate_app_id,
)

#: Same typo-guard reasoning as `gate.store_scope`'s malformed-field check
#: (B-25): an operator toggling a misspelled permission name would otherwise
#: believe they granted or revoked something, and nothing would happen.
KNOWN_PERMISSIONS = frozenset(PERMISSION_GROUPS) | {NET_PERMISSION, INTEGRATION_NET_PERMISSION, WEB_NET_PERMISSION}


def manifest_path(app_id: str) -> Path:
    return _apps_root() / _validate_app_id(app_id) / "manifest.json"


def _write_json_atomic(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def read_manifest(app_id: str) -> dict:
    """This app's manifest, or `{"permissions": []}` if none exists yet."""
    path = manifest_path(app_id)
    if not path.is_file():
        return {"permissions": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path} top level is not an object")
    data.setdefault("permissions", [])
    return data


def set_permission(app_id: str, perm: str, granted: bool) -> dict:
    """Add or remove `perm` from an app's manifest `permissions` list.

    Creates the manifest if this is its first permission. Raises on an
    unknown permission name rather than silently writing (and matching)
    nothing.

    Revoking from an app with no manifest is a deliberate no-op that writes
    nothing: `gate.store_scope` treats "no manifest" as deny-all but a
    manifest with an empty `permissions` list and no `store_scope` field as
    *unrestricted* — materializing an empty manifest here would turn a
    no-op revoke into a store-access grant nobody asked for.
    """
    if perm not in KNOWN_PERMISSIONS:
        raise ValueError(
            f"unknown permission {perm!r} — expected one of {sorted(KNOWN_PERMISSIONS)}"
        )
    existed = manifest_path(app_id).is_file()
    manifest = read_manifest(app_id)
    perms = list(manifest.get("permissions") or [])
    changed = False
    if granted:
        if perm not in perms:
            perms.append(perm)
            changed = True
    elif perm in perms:
        perms = [p for p in perms if p != perm]
        changed = True

    if not existed and not changed:
        return manifest

    manifest["permissions"] = perms
    _write_json_atomic(manifest_path(_validate_app_id(app_id)), manifest)
    return manifest
