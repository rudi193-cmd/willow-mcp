"""Agent-agnostic IDE wiring for willow-mcp managed projects.

Materializes Cursor hooks, Claude settings, and active-agent markers from
``src/willow_mcp/deploy/`` templates — not fleet fylgja hooks.
"""
from __future__ import annotations

import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any

_HOME_VAR = "{{HOME}}"

_DEFAULT_WIRING: dict[str, Any] = {
    "hooks": True,
    "active_agent": True,
    "claude_settings": "project",
}

_DESTRUCTIVE_WILLOW_DENY = [
    "mcp__willow__app_uninstall",
    "mcp__willow__policy_put",
    "mcp__willow__policy_delete",
    "mcp__willow__routine_register",
]


def deploy_dir() -> Path:
    return Path(__file__).resolve().parent / "deploy"


def expand_home(text: str) -> str:
    home = str(Path.home())
    return text.replace(_HOME_VAR, home).replace("${HOME}", home).replace("$HOME", home)


def resolve_willow_mcp_python() -> str:
    raw = os.environ.get("WILLOW_MCP_PYTHON", "").strip()
    if raw:
        return expand_home(raw)
    candidates = [
        Path.home() / "github" / ".willow" / "venvs" / "willow-mcp" / "bin" / "python",
        shutil.which("python3"),
        sys.executable,
    ]
    for candidate in candidates:
        if not candidate:
            continue
        path = Path(str(candidate))
        if path.is_file():
            return str(path.resolve())
    return sys.executable


def _substitute_placeholders(obj: Any, values: dict[str, str]) -> Any:
    if isinstance(obj, str):
        out = obj
        for key, val in values.items():
            out = out.replace(f"{{{{{key}}}}}", val)
        return out
    if isinstance(obj, list):
        return [_substitute_placeholders(x, values) for x in obj]
    if isinstance(obj, dict):
        return {k: _substitute_placeholders(v, values) for k, v in obj.items()}
    return obj


def render_claude_permissions(servers: list[str]) -> dict[str, Any]:
    allow = [
        "Read(*)",
        "Edit(*)",
        "Write(*)",
        "Glob(*)",
        "Grep(*)",
        "Skill(*)",
        "Task(*)",
    ]
    for name in servers:
        if isinstance(name, str) and name:
            allow.append(f"mcp__{name}__*")
    allow.append("mcp__claude_ai_Grove__*")
    seen: set[str] = set()
    deduped: list[str] = []
    for item in allow:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)

    deny = list(_DESTRUCTIVE_WILLOW_DENY) if "willow" in servers else []
    enabled = [s for s in servers if isinstance(s, str)]
    return {
        "permissions": {"allow": deduped, "deny": deny},
        "enableAllProjectMcpServers": True,
        "enabledMcpjsonServers": enabled,
    }


def normalize_wiring(entry: dict[str, Any]) -> dict[str, Any]:
    if "wiring" not in entry:
        return {k: False for k in _DEFAULT_WIRING}
    raw = entry.get("wiring")
    if raw is False:
        return {k: False for k in _DEFAULT_WIRING}
    if not isinstance(raw, dict):
        return dict(_DEFAULT_WIRING)
    out = dict(_DEFAULT_WIRING)
    out.update(raw)
    return out


def render_cursor_hooks() -> dict[str, Any]:
    template = json.loads((deploy_dir() / "hooks.json").read_text(encoding="utf-8"))
    return _substitute_placeholders(
        template,
        {"WILLOW_MCP_PYTHON": resolve_willow_mcp_python()},
    )


def runtime_env(agent: str, entry: dict[str, Any]) -> dict[str, str]:
    from .paths import store_root, willow_home

    env: dict[str, str] = {
        "WILLOW_AGENT_NAME": agent,
        "AGENT_NAME": agent,
        "WILLOW_APP_ID": agent,
        "WILLOW_HOME": str(willow_home().resolve()),
        "WILLOW_STORE_ROOT": str(store_root().resolve()),
        "WILLOW_MCP_PYTHON": resolve_willow_mcp_python(),
    }
    overrides = entry.get("env") if isinstance(entry.get("env"), dict) else {}
    for key, val in overrides.items():
        if isinstance(val, str):
            if key == "WILLOW_STORE_ROOT" and "github/willow/.willow/store" in expand_home(val):
                continue
            env[key] = expand_home(val)
    return env


def render_project_claude_settings(
    entry: dict[str, Any],
) -> dict[str, Any]:
    agent = str(entry.get("agent") or "willow").strip()
    servers = [s for s in (entry.get("servers") or []) if isinstance(s, str)]
    template = json.loads((deploy_dir() / "claude-settings.json").read_text(encoding="utf-8"))
    payload = render_claude_permissions(servers)
    payload["hooks"] = template.get("hooks", {})
    payload["env"] = runtime_env(agent, entry)
    return _substitute_placeholders(
        payload,
        {"WILLOW_MCP_PYTHON": resolve_willow_mcp_python()},
    )


def wiring_paths(project_id: str, entry: dict[str, Any]) -> dict[str, Path]:
    raw = str(entry.get("path") or "").strip()
    if not raw:
        raise ValueError(f"project {project_id!r}: path required")
    root = Path(expand_home(raw)).resolve()
    return {
        "root": root,
        "active_agent": root / ".willow" / "active-agent",
        "cursor_hooks": root / ".cursor" / "hooks.json",
        "claude_settings": root / ".claude" / "settings.local.json",
    }


def write_active_agent(project_root: Path, agent: str) -> None:
    path = project_root / ".willow" / "active-agent"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(agent.strip() + "\n", encoding="utf-8")


def _write_json(path: Path, data: dict, *, dry_run: bool) -> None:
    if dry_run:
        print(f"[project_wiring] Would write {path}")
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)
    print(f"[project_wiring] Wrote {path}")


def _normalize_json(data: dict) -> str:
    return json.dumps(data, sort_keys=True, indent=2) + "\n"


def _read_json(path: Path) -> dict | None:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def audit_project_wiring(
    project_id: str,
    entry: dict[str, Any],
) -> list[str]:
    wiring = normalize_wiring(entry)
    if not any(wiring.values()):
        return []

    issues: list[str] = []
    paths = wiring_paths(project_id, entry)
    ides = entry.get("ides") or []
    agent = str(entry.get("agent") or "willow").strip()

    if not paths["root"].is_dir():
        issues.append(f"{project_id}: path does not exist → {paths['root']}")
        return issues

    if wiring.get("active_agent"):
        if not paths["active_agent"].is_file():
            issues.append(f"{project_id}: missing active-agent → {paths['active_agent']}")
        else:
            on_disk = paths["active_agent"].read_text(encoding="utf-8").strip()
            if on_disk != agent:
                issues.append(
                    f"{project_id}: active-agent drift (want {agent!r}, got {on_disk!r})"
                )

    if wiring.get("hooks") and "cursor" in ides:
        expected = render_cursor_hooks()
        on_disk = _read_json(paths["cursor_hooks"])
        if on_disk is None:
            issues.append(f"{project_id}: missing cursor hooks → {paths['cursor_hooks']}")
        elif _normalize_json(on_disk) != _normalize_json(expected):
            issues.append(f"{project_id}: cursor hooks drift → {paths['cursor_hooks']}")

    if wiring.get("claude_settings") == "project" and "claude" in ides:
        expected = render_project_claude_settings(entry)
        on_disk = _read_json(paths["claude_settings"])
        if on_disk is None:
            issues.append(f"{project_id}: missing claude settings → {paths['claude_settings']}")
        else:
            for key in ("env", "permissions", "enableAllProjectMcpServers", "enabledMcpjsonServers", "hooks"):
                if on_disk.get(key) != expected.get(key):
                    issues.append(
                        f"{project_id}: claude settings drift ({key}) → {paths['claude_settings']}"
                    )
                    break

    return issues


def sync_project_wiring(
    project_id: str,
    entry: dict[str, Any],
    *,
    dry_run: bool = False,
) -> None:
    wiring = normalize_wiring(entry)
    if not any(wiring.values()):
        return

    paths = wiring_paths(project_id, entry)
    ides = entry.get("ides") or []
    agent = str(entry.get("agent") or "willow").strip()

    paths["root"].mkdir(parents=True, exist_ok=True)

    if wiring.get("active_agent"):
        if dry_run:
            print(f"[project_wiring] Would write {paths['active_agent']} → {agent}")
        else:
            write_active_agent(paths["root"], agent)
            print(f"[project_wiring] Wrote {paths['active_agent']}")

    if wiring.get("hooks") and "cursor" in ides:
        _write_json(paths["cursor_hooks"], render_cursor_hooks(), dry_run=dry_run)

    if wiring.get("claude_settings") == "project" and "claude" in ides:
        _write_json(
            paths["claude_settings"],
            render_project_claude_settings(entry),
            dry_run=dry_run,
        )
