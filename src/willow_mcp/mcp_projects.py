"""Fleet MCP project registry: render + sync per-repo IDE configs (agent-agnostic).

Registry lives at ``$WILLOW_HOME/mcp/projects.json`` (seed:
``src/willow_mcp/deploy/mcp_projects.seed.json``).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import egress_setup
from .paths import store_root, willow_home
from .project_wiring import (
    expand_home,
    normalize_wiring,
    render_project_claude_settings,
    resolve_willow_mcp_python,
)

_STATIC_SERVERS: dict[str, dict[str, Any]] = {
    "codebase-memory-mcp": {
        "type": "stdio",
        "command": "${HOME}/.local/bin/codebase-memory-mcp",
        "args": [],
    },
}


def deploy_dir() -> Path:
    return Path(__file__).resolve().parent / "deploy"


def seed_path() -> Path:
    return deploy_dir() / "mcp_projects.seed.json"


def registry_path() -> Path:
    return willow_home() / "mcp" / "projects.json"


def expand_home_in_obj(obj: Any) -> Any:
    if isinstance(obj, str):
        return expand_home(obj)
    if isinstance(obj, list):
        return [expand_home_in_obj(x) for x in obj]
    if isinstance(obj, dict):
        return {k: expand_home_in_obj(v) for k, v in obj.items()}
    return obj


def _write_json(path: Path, data: dict, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[mcp_projects] Would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"[mcp_projects] Wrote {path}")


def load_seed() -> dict:
    return json.loads(seed_path().read_text(encoding="utf-8"))


def ensure_registry(*, dry_run: bool = False) -> Path:
    """Copy seed → fleet home if projects.json missing."""
    dest = registry_path()
    if dest.is_file():
        return dest
    seed = load_seed()
    _write_json(dest, seed, dry_run=dry_run)
    return dest


_PRODUCT_PROJECTS = ("willow", "github")


def merge_product_projects_from_seed(registry: dict, *, persist: bool = False) -> dict:
    """Overlay willow-mcp product entries onto the fleet registry."""
    seed = load_seed()
    projects = registry.setdefault("projects", {})
    changed = False
    for pid in _PRODUCT_PROJECTS:
        if pid not in projects:
            continue
        entry = seed.get("projects", {}).get(pid)
        if isinstance(entry, dict) and projects.get(pid) != entry:
            projects[pid] = entry
            changed = True
    if changed and persist:
        _write_json(registry_path(), registry, dry_run=False)
    return registry


def load_registry(*, bootstrap: bool = True) -> dict:
    path = registry_path()
    if not path.is_file():
        if bootstrap:
            ensure_registry(dry_run=False)
        else:
            raise FileNotFoundError(f"MCP registry missing: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("projects"), dict):
        raise ValueError(f"Invalid registry (missing projects): {path}")
    return merge_product_projects_from_seed(data, persist=True)


def list_projects() -> list[dict[str, Any]]:
    reg = load_registry()
    rows: list[dict[str, Any]] = []
    for pid, entry in sorted(reg.get("projects", {}).items()):
        if not isinstance(entry, dict):
            continue
        rows.append(
            {
                "id": pid,
                "path": entry.get("path", ""),
                "agent": entry.get("agent", ""),
                "servers": list(entry.get("servers") or []),
                "ides": list(entry.get("ides") or []),
                "note": entry.get("note", ""),
                "wiring": normalize_wiring(entry),
            }
        )
    return rows


def _egress_public_key_env() -> dict[str, str]:
    pub = egress_setup.resolve_public_key_path()
    if pub is not None and pub.is_file():
        return {"WILLOW_MCP_EGRESS_PUBLIC_KEY": str(pub.resolve())}
    return {}


def _skip_store_override(
    key: str, val: str, entry: dict[str, Any], *, project_id: str
) -> bool:
    if key != "WILLOW_STORE_ROOT" or project_id != "willow":
        return False
    expanded = expand_home(val)
    if "github/willow/.willow/store" in expanded:
        return True
    raw_path = str(entry.get("path") or "").strip()
    if raw_path:
        project_root = Path(expand_home(raw_path)).resolve()
        try:
            if Path(expanded).resolve() == (project_root / ".willow" / "store").resolve():
                return True
        except OSError:
            pass
    return False


def _willow_mcp_server_block(
    *,
    project_id: str,
    agent: str,
    entry: dict[str, Any],
    extra_env: dict[str, Any] | None = None,
    human_orchestrator: bool = False,
) -> dict[str, Any]:
    env: dict[str, str] = {
        "WILLOW_APP_ID": agent,
        "WILLOW_PG_DB": "willow_20",
        "WILLOW_HOME": str(willow_home().resolve()),
        "WILLOW_STORE_ROOT": str(store_root().resolve()),
    }
    if human_orchestrator or agent.strip().lower() == "willow":
        env["WILLOW_HUMAN_ORCHESTRATOR"] = "1"
    env.update(_egress_public_key_env())
    for key, val in (extra_env or {}).items():
        if isinstance(val, str):
            if _skip_store_override(key, val, entry, project_id=project_id):
                continue
            env[key] = expand_home(val)
    return {
        "type": "stdio",
        "command": resolve_willow_mcp_python(),
        "args": ["-m", "willow_mcp"],
        "env": env,
    }


def _static_server_block(name: str, extra_env: dict[str, Any] | None = None) -> dict[str, Any]:
    if name not in _STATIC_SERVERS:
        raise ValueError(f"unknown static server {name!r}")
    block = json.loads(json.dumps(_STATIC_SERVERS[name]))
    if extra_env:
        env = block.setdefault("env", {})
        if isinstance(env, dict):
            for key, val in extra_env.items():
                if isinstance(val, str):
                    env[key] = expand_home(val)
    return block


def render_project_mcp(
    project_id: str,
    entry: dict[str, Any],
) -> dict[str, Any]:
    agent = str(entry.get("agent") or "willow").strip()
    servers = entry.get("servers") or []
    if not isinstance(servers, list) or not servers:
        raise ValueError(f"project {project_id!r}: servers[] required")

    willow_env = dict(entry.get("env") if isinstance(entry.get("env"), dict) else {})
    raw_path = str(entry.get("path") or "").strip()
    if raw_path:
        willow_env.setdefault("WILLOW_PROJECT_ROOT", raw_path)
    willow_env.setdefault("WILLOW_HANDOFF_PROJECT", project_id)
    server_env = entry.get("server_env") if isinstance(entry.get("server_env"), dict) else {}

    mcp_servers: dict[str, Any] = {}
    for name in servers:
        if not isinstance(name, str):
            continue
        if name == "willow-mcp":
            mcp_servers["willow-mcp"] = _willow_mcp_server_block(
                project_id=project_id,
                agent=agent,
                entry=entry,
                extra_env=willow_env,
                human_orchestrator=agent.strip().lower() == "willow",
            )
        elif name in _STATIC_SERVERS:
            overrides = server_env.get(name) if isinstance(server_env.get(name), dict) else {}
            mcp_servers[name] = _static_server_block(name, overrides)
        else:
            raise ValueError(f"project {project_id!r}: unknown server {name!r}")

    return {"mcpServers": mcp_servers}


def render_charter_codex_config(
    project_id: str,
    entry: dict[str, Any],
) -> str:
    """Codex MCP fragment for the charter Jarvis seat."""
    if project_id != "willow":
        raise ValueError(f"charter codex template only applies to project 'willow', not {project_id!r}")
    template = (deploy_dir() / "charter-codex-mcp.toml.template").read_text(encoding="utf-8")
    agent = str(entry.get("agent") or "willow").strip()
    env_overrides = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    store = str(env_overrides.get("WILLOW_STORE_ROOT") or str(store_root().resolve()))
    project_root = str(env_overrides.get("WILLOW_PROJECT_ROOT") or "{{HOME}}/github/willow")
    handoff = str(env_overrides.get("WILLOW_HANDOFF_PROJECT") or project_id)
    values = {
        "AGENT_NAME": agent,
        "WILLOW_HOME": str(willow_home().resolve()),
        "WILLOW_MCP_PYTHON": resolve_willow_mcp_python(),
        "WILLOW_STORE_ROOT": expand_home(store),
        "WILLOW_PROJECT_ROOT": expand_home(project_root),
        "WILLOW_HANDOFF_PROJECT": handoff,
    }
    out = template
    for key, val in values.items():
        out = out.replace(f"{{{{{key}}}}}", val)
    return out.rstrip() + "\n"


def project_paths(project_id: str, entry: dict[str, Any]) -> dict[str, Path]:
    raw = str(entry.get("path") or "").strip()
    if not raw:
        raise ValueError(f"project {project_id!r}: path required")
    root = Path(expand_home(raw)).resolve()
    home_mcp = willow_home() / "mcp" / f"{project_id}.mcp.json"
    return {
        "root": root,
        "canonical": home_mcp,
        "cursor": root / ".cursor" / "mcp.json",
        "claude_mcp": root / ".mcp.json",
        "claude_settings": root / ".claude" / "settings.local.json",
        "codex_config": root / ".codex" / "config.toml",
    }


def _normalize_mcp_json(data: dict) -> str:
    canonical = expand_home_in_obj(data)
    return json.dumps(canonical, sort_keys=True, indent=2) + "\n"


def audit_project(
    project_id: str,
    entry: dict[str, Any],
) -> list[str]:
    """Return drift messages (empty = in sync)."""
    from .project_wiring import audit_project_wiring

    issues: list[str] = []
    expected = render_project_mcp(project_id, entry)
    paths = project_paths(project_id, entry)
    expected_text = _normalize_mcp_json(expected)

    for label, path in (
        ("canonical", paths["canonical"]),
        ("cursor", paths["cursor"]),
        ("claude_mcp", paths["claude_mcp"]),
    ):
        if not path.is_file():
            issues.append(f"{project_id}: missing {label} → {path}")
            continue
        try:
            on_disk = json.loads(path.read_text(encoding="utf-8"))
        except Exception as e:
            issues.append(f"{project_id}: unreadable {label} ({path}): {e}")
            continue
        if _normalize_mcp_json(on_disk) != expected_text:
            issues.append(f"{project_id}: drift {label} → {path}")

    ides = entry.get("ides") or []
    wiring = normalize_wiring(entry)
    if "claude" in ides and wiring.get("claude_settings") == "project":
        settings = paths["claude_settings"]
        expected_settings = render_project_claude_settings(entry)
        if not settings.is_file():
            issues.append(f"{project_id}: missing claude settings → {settings}")
        else:
            try:
                on_disk = json.loads(settings.read_text(encoding="utf-8"))
            except Exception as e:
                issues.append(f"{project_id}: unreadable claude settings: {e}")
            else:
                for key in ("permissions", "enableAllProjectMcpServers", "enabledMcpjsonServers", "hooks", "env"):
                    if on_disk.get(key) != expected_settings.get(key):
                        issues.append(
                            f"{project_id}: claude settings drift ({key}) → {settings}"
                        )
                        break

    issues.extend(audit_project_wiring(project_id, entry))

    proj_path = paths["root"]
    if not proj_path.is_dir():
        issues.append(f"{project_id}: path does not exist → {proj_path}")

    return issues


def sync_project(
    project_id: str,
    entry: dict[str, Any],
    *,
    dry_run: bool = False,
) -> dict[str, Path]:
    from .project_wiring import sync_project_wiring

    payload = render_project_mcp(project_id, entry)
    paths = project_paths(project_id, entry)
    ides = entry.get("ides") or []

    for label, path in (
        ("canonical", paths["canonical"]),
        ("cursor", paths["cursor"] if "cursor" in ides else None),
        ("claude_mcp", paths["claude_mcp"] if "claude" in ides else None),
    ):
        if path is None:
            continue
        _write_json(path, payload, dry_run=dry_run)

    wiring = normalize_wiring(entry)
    if "claude" in ides and wiring.get("claude_settings") == "project":
        _write_json(
            paths["claude_settings"],
            render_project_claude_settings(entry),
            dry_run=dry_run,
        )

    if "codex" in ides and project_id == "willow":
        codex_path = paths.get("codex_config")
        if codex_path is not None:
            text = render_charter_codex_config(project_id, entry)
            if dry_run:
                print(f"[mcp_projects] Would write {codex_path}")
            else:
                codex_path.parent.mkdir(parents=True, exist_ok=True)
                codex_path.write_text(text, encoding="utf-8")
                print(f"[mcp_projects] Wrote {codex_path}")

    sync_project_wiring(project_id, entry, dry_run=dry_run)

    return paths


def sync_all(
    *,
    project_ids: list[str] | None = None,
    dry_run: bool = False,
) -> list[str]:
    reg = load_registry()
    projects: dict[str, Any] = reg.get("projects", {})
    selected = project_ids or sorted(projects.keys())
    written: list[str] = []
    for pid in selected:
        entry = projects.get(pid)
        if not isinstance(entry, dict):
            raise KeyError(f"Unknown project {pid!r}")
        sync_project(pid, entry, dry_run=dry_run)
        written.append(pid)
    return written


def audit_all(
    *,
    project_ids: list[str] | None = None,
) -> list[str]:
    reg = load_registry()
    projects: dict[str, Any] = reg.get("projects", {})
    selected = project_ids or sorted(projects.keys())
    issues: list[str] = []
    seen_roots: dict[Path, str] = {}
    for pid in selected:
        entry = projects.get(pid)
        if not isinstance(entry, dict):
            issues.append(f"Unknown project {pid!r}")
            continue
        raw = str(entry.get("path") or "").strip()
        if raw:
            resolved = Path(expand_home(raw)).resolve()
            prior = seen_roots.get(resolved)
            if prior is not None:
                continue
            seen_roots[resolved] = pid
        issues.extend(audit_project(pid, entry))
    return issues
