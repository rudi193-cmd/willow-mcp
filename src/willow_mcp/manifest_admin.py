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

from . import pgp
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

    # Nothing to write, whether or not the file is there. The `not existed` half
    # is the documented one above; the `existed` half matters under PGP
    # enforcement, where falling through would rewrite identical content, discard
    # the valid signature that content already has, and re-sign — turning
    # `allow-permission` from an idempotent command into one that invokes gpg and
    # *raises* on a re-grant that changes nothing.
    if not changed:
        return manifest

    manifest["permissions"] = perms
    path = manifest_path(_validate_app_id(app_id))
    previous = path.read_text(encoding="utf-8") if existed else None
    _write_json_atomic(path, manifest)

    # Under PGP enforcement the manifest's authority comes from its detached
    # signature, and rewriting the file invalidates it. Writing and walking away
    # would silently revoke the app's entire gate -- the operator's own supported
    # edit path taking the fleet down, with nothing said. Re-sign, or put the file
    # back exactly as it was and refuse: a half-applied permission change that
    # leaves an unsigned manifest is strictly worse than no change at all.
    if pgp.pgp_enabled():
        ok, detail = pgp.sign_detached(path)
        if not ok:
            if previous is None:
                path.unlink(missing_ok=True)
            else:
                path.write_text(previous, encoding="utf-8")
            raise RuntimeError(
                f"permission change rolled back: manifest for {app_id!r} could not be "
                f"re-signed and an unsigned manifest is denied everywhere ({detail}). "
                f"Sign from a host terminal with a reachable gpg-agent, or unset "
                f"WILLOW_PGP_FINGERPRINT to run without enforcement."
            )
    return manifest
