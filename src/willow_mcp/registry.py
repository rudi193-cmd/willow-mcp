"""Specialist registry loader and manifest compiler.

Source of truth: bundle/config/specialists.json (shipped) or
$WILLOW_HOME/config/specialists.json (operator overlay after init).

See docs/design/specialist-registry.md and permissions-matrix.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator

from .paths import bundle_dir, mcp_app_dir, specialists_config_path, willow_home

REGISTRY_FORMAT = "specialist_registry_v1"


def registry_path(prefer_home: bool = True) -> Path:
    """Resolve registry JSON: home overlay when present, else bundle seed."""
    home_path = specialists_config_path()
    if prefer_home and home_path.is_file():
        return home_path
    bundle_path = bundle_dir() / "config" / "specialists.json"
    if bundle_path.is_file():
        return bundle_path
    return home_path


def load_registry(*, path: Path | None = None, prefer_home: bool = True) -> dict[str, Any]:
    src = path or registry_path(prefer_home=prefer_home)
    if not src.is_file():
        return {"format": REGISTRY_FORMAT, "specialists": []}
    data = json.loads(src.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"registry must be a JSON object: {src}")
    return data


def iter_registry_rows(registry: dict[str, Any]) -> Iterator[dict[str, Any]]:
    for row in registry.get("specialists") or []:
        if isinstance(row, dict):
            yield row
    orch = registry.get("orchestrator_seat")
    if isinstance(orch, dict):
        yield orch


def manifest_from_row(row: dict[str, Any]) -> dict[str, Any]:
    """Build an mcp_apps manifest dict from a registry row."""
    agent_id = row.get("agent_id")
    if not agent_id:
        raise ValueError("registry row missing agent_id")

    manifest: dict[str, Any] = {
        "app_id": agent_id,
        "human_only": bool(row.get("human_only", False)),
        "role": row.get("role", ""),
        "permissions": list(row.get("permissions") or []),
        "deny_tools": list(row.get("deny_tools") or []),
    }
    store_scope = row.get("store_scope")
    if store_scope is not None:
        manifest["store_scope"] = list(store_scope)
    return manifest


def compile_manifests(
    registry: dict[str, Any] | None = None,
    *,
    only_missing: bool = False,
    dry_run: bool = False,
) -> dict[str, list[str]]:
    """Write manifests under $WILLOW_HOME/mcp_apps from registry rows."""
    reg = registry if registry is not None else load_registry()
    written: list[str] = []
    skipped: list[str] = []

    for row in iter_registry_rows(reg):
        agent_id = str(row.get("agent_id", "")).strip()
        if not agent_id:
            continue
        manifest_path = mcp_app_dir(agent_id) / "manifest.json"
        rel = str(manifest_path.relative_to(willow_home()))

        if only_missing and manifest_path.exists():
            skipped.append(rel)
            continue

        manifest = manifest_from_row(row)
        if dry_run:
            written.append(rel)
            continue

        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        written.append(rel)

    return {"written": written, "skipped": skipped}


def compile_agents_main(
    *,
    force: bool = False,
    dry_run: bool = False,
    registry_file: Path | None = None,
) -> dict[str, Any]:
    reg = load_registry(path=registry_file) if registry_file else load_registry()
    result = compile_manifests(reg, only_missing=not force, dry_run=dry_run)
    return {
        "registry": str(registry_file or registry_path()),
        "dry_run": dry_run,
        "force": force,
        **result,
    }
