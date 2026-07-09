"""Scaffold $WILLOW_HOME for the standalone willow-mcp product.

Idempotent: creates directories, writes default config only when missing,
copies bundled seeds (templates, skills, hooks) without overwriting operator files.

See docs/design/product-layout.md (LOCKED).
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

from .paths import (
    LAYOUT_VERSION,
    agent_roster_path,
    all_layout_dirs,
    bundle_dir,
    layout_version_path,
    mcp_app_dir,
    persona_envelopes_path,
    personas_dir,
    rotation_path,
    seeds_dir,
    specialists_config_path,
    settings_global_path,
    willow_home,
)
from .human_session import ORCHESTRATOR_APP_ID

_DEFAULT_ROSTER: dict[str, Any] = {
    "format": "agent_roster_v1",
    "agents": [
        {"id": "willow", "role": "orchestrator", "default_app_id": "willow"},
        {"id": "hanuman", "role": "builder", "default_app_id": "hanuman"},
        {"id": "loki", "role": "auditor", "default_app_id": "loki"},
        {"id": "jeles", "role": "librarian", "default_app_id": "jeles"},
        {"id": "ada", "role": "operator", "default_app_id": "ada"},
    ],
}

_DEFAULT_ENVELOPES: dict[str, Any] = {
    "format": "persona_envelopes_v1",
    "note": "Tool ACL per role — not charter pre-approved.json authority grants.",
    "roles": {
        "orchestrator": {"allow_groups": ["orchestrator", "full_access"]},
        "builder": {"allow_groups": ["dispatch_write", "task_queue", "store_read", "knowledge_read"]},
        "auditor": {"allow_groups": ["dispatch_read", "dispatch_write", "knowledge_read"]},
        "librarian": {"allow_groups": ["dispatch_read", "dispatch_write", "knowledge_read"]},
        "operator": {"allow_groups": ["dispatch_read", "fleet_read", "knowledge_read"]},
    },
}

_DEFAULT_SETTINGS: dict[str, Any] = {
    "consent": {
        "internet": False,
        "cloud_llm": False,
        "lan": False,
    },
}

_DEFAULT_ROTATION: dict[str, Any] = {
    "format": "rotation_v1",
    "providers": {},
}

_DEFAULT_WILLOW_MANIFEST: dict[str, Any] = {
    "app_id": ORCHESTRATOR_APP_ID,
    "human_only": True,
    "role": "orchestrator",
    "permissions": ["orchestrator", "dispatch_read", "context", "store_read", "knowledge_read"],
    "store_scope": ["willow_*", "projects_*"],
}


def _load_bundle_specialists() -> dict[str, Any]:
    path = bundle_dir() / "config" / "specialists.json"
    if not path.is_file():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def _manifest_from_registry_row(row: dict[str, Any]) -> dict[str, Any]:
    return {
        "app_id": row["agent_id"],
        "human_only": bool(row.get("human_only", False)),
        "role": row.get("role", ""),
        "permissions": list(row.get("permissions") or []),
        "store_scope": list(row.get("store_scope") or []),
    }


def _copy_bundle_file_if_missing(src: Path, dest: Path) -> bool:
    if not src.is_file() or dest.exists():
        return False
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    return True


def _materialize_registry() -> dict[str, list[str]]:
    """Copy specialists registry, personas, seed template, and per-agent manifests."""
    created: list[str] = []
    registry = _load_bundle_specialists()
    if registry and _write_json_if_missing(specialists_config_path(), registry):
        created.append(str(specialists_config_path().relative_to(willow_home())))

    personas_copied = _copy_bundle_tree("personas", personas_dir())
    seeds_copied: list[str] = []
    seed_tpl = bundle_dir() / "seeds" / "agent-seed-template.json"
    seed_dest = seeds_dir() / "agent-seed-template.json"
    if _copy_bundle_file_if_missing(seed_tpl, seed_dest):
        seeds_copied.append(str(seed_dest.relative_to(willow_home())))

    manifests_created: list[str] = []
    rows: list[dict[str, Any]] = list(registry.get("specialists") or [])
    orch = registry.get("orchestrator_seat")
    if isinstance(orch, dict):
        rows.append(orch)

    for row in rows:
        agent_id = row.get("agent_id")
        if not agent_id:
            continue
        manifest_path = mcp_app_dir(str(agent_id)) / "manifest.json"
        manifest = _manifest_from_registry_row(row)
        if _write_json_if_missing(manifest_path, manifest):
            manifests_created.append(str(manifest_path.relative_to(willow_home())))

    return {
        "registry_config_created": created,
        "personas_copied": personas_copied,
        "seeds_copied": seeds_copied,
        "manifests_created": manifests_created,
    }


def _write_json_if_missing(path: Path, data: dict) -> bool:
    if path.exists():
        return False
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def _copy_bundle_tree(subdir: str, dest: Path) -> list[str]:
    """Copy files from package bundle/{subdir}/ to dest. Returns copied paths."""
    src_root = bundle_dir() / subdir
    if not src_root.is_dir():
        return []
    copied: list[str] = []
    dest.mkdir(parents=True, exist_ok=True)
    for src in src_root.rglob("*"):
        if not src.is_file():
            continue
        rel = src.relative_to(src_root)
        target = dest / rel
        if target.exists():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
        copied.append(str(target.relative_to(willow_home())))
    return copied


def ensure_home_layout(home: Path | None = None) -> dict[str, Any]:
    """Create the locked product tree under $WILLOW_HOME. Safe to call repeatedly."""
    if home is not None:
        import os

        os.environ["WILLOW_HOME"] = str(home)

    created_dirs: list[str] = []
    for d in all_layout_dirs():
        if not d.exists():
            d.mkdir(parents=True, exist_ok=True)
            created_dirs.append(str(d.relative_to(willow_home())))

    config_created: list[str] = []
    if _write_json_if_missing(settings_global_path(), _DEFAULT_SETTINGS):
        config_created.append(str(settings_global_path().relative_to(willow_home())))
    if _write_json_if_missing(agent_roster_path(), _DEFAULT_ROSTER):
        config_created.append(str(agent_roster_path().relative_to(willow_home())))
    if _write_json_if_missing(persona_envelopes_path(), _DEFAULT_ENVELOPES):
        config_created.append(str(persona_envelopes_path().relative_to(willow_home())))
    if _write_json_if_missing(rotation_path(), _DEFAULT_ROTATION):
        config_created.append(str(rotation_path().relative_to(willow_home())))

    review_q = willow_home() / "constitutional" / "review_queue.json"
    if _write_json_if_missing(review_q, {"format": "review_queue_v1", "items": []}):
        config_created.append(str(review_q.relative_to(willow_home())))

    manifest_path = mcp_app_dir(ORCHESTRATOR_APP_ID) / "manifest.json"
    if _write_json_if_missing(manifest_path, _DEFAULT_WILLOW_MANIFEST):
        config_created.append(str(manifest_path.relative_to(willow_home())))

    registry_result = _materialize_registry()
    # orchestrator manifest may also be created by registry pass; dedupe in output
    for path in registry_result.get("registry_config_created") or []:
        if path not in config_created:
            config_created.append(path)

    seeds: dict[str, list[str]] = {
        "templates": _copy_bundle_tree("templates", willow_home() / "templates"),
        "skills": _copy_bundle_tree("skills", willow_home() / "skills"),
        "hooks": _copy_bundle_tree("hooks", willow_home() / "hooks"),
    }

    layout_version_path().write_text(f"{LAYOUT_VERSION}\n", encoding="utf-8")

    return {
        "home": str(willow_home()),
        "layout_version": LAYOUT_VERSION,
        "dirs_created": created_dirs,
        "config_created": config_created,
        "seeds_copied": seeds,
        "registry": registry_result,
    }


def main() -> None:
    result = ensure_home_layout()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
