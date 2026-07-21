"""B-32: operator tooling to separate confirm authority from the agent process.

The agent may REQUEST egress; only the operator (via a uid the agent does not
share write access with) may CONFIRM it. ``harden-trust-root`` chowns the trust
roots and wires ``WILLOW_MCP_STRICT_TRUST_ROOT=1`` into MCP configs.
"""

from __future__ import annotations

import json
import os
import pwd
import shutil
import subprocess
from pathlib import Path
from typing import Any

from . import consent
from . import lease
from . import paths


STRICT_ENV_KEY = "WILLOW_MCP_STRICT_TRUST_ROOT"
DEFAULT_TRUST_OWNER = "willow-operator"


def default_trust_owner() -> str:
    return os.environ.get("WILLOW_MCP_TRUST_OWNER", "").strip() or DEFAULT_TRUST_OWNER


def trust_root_directories() -> list[Path]:
    """Top-level directories whose contents authorize egress or policy."""
    roots = [paths.mcp_apps_root(), paths.config_dir()]
    for candidate in (
        paths.settings_global_legacy_path(),
        paths.consent_legacy_path(),
    ):
        if candidate.is_file():
            roots.append(candidate.parent)
    # De-dupe while preserving order (home root may appear twice).
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def consent_policy_paths() -> list[Path]:
    paths_out = [consent.settings_path(), consent.legacy_path()]
    seen: set[str] = set()
    unique: list[Path] = []
    for path in paths_out:
        key = str(path)
        if key not in seen:
            seen.add(key)
            unique.append(path)
    return unique


def audit_trust_root(app_id: str = "") -> dict[str, Any]:
    """Report forgeable trust paths and whether strict separation is active."""
    forgeable = list(lease.self_writable_trust_paths(app_id))
    consent_writable: list[dict[str, str]] = []
    for path in consent_policy_paths():
        try:
            if lease.path_is_self_writable_or_replaceable(path):
                consent_writable.append({"key": "consent", "path": str(path)})
        except OSError:
            consent_writable.append({"key": "consent", "path": str(path)})

    strict = lease.strict_trust_root()
    all_forgeable = forgeable + consent_writable
    return {
        "strict_trust_root": strict,
        "forgeable": all_forgeable,
        "hardened": strict and not all_forgeable,
        "trust_roots": [str(p) for p in trust_root_directories()],
        "trust_owner_hint": default_trust_owner(),
    }


def mcp_env_snippet() -> dict[str, str]:
    return {STRICT_ENV_KEY: "1"}


def merge_mcp_env(path: Path, env: dict[str, str]) -> bool:
    if not env or not path.is_file():
        return False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    servers = data.get("mcpServers")
    if not isinstance(servers, dict):
        return False
    entry = servers.get("willow-mcp")
    if not isinstance(entry, dict):
        return False
    entry_env = entry.setdefault("env", {})
    if not isinstance(entry_env, dict):
        return False
    entry_env.update(env)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return True


def project_mcp_json_paths(project_root: Path) -> list[Path]:
    root = project_root.expanduser().resolve()
    return [root / ".cursor" / "mcp.json", root / ".mcp.json"]


def resolve_trust_owner(owner: str) -> str:
    name = (owner or default_trust_owner()).strip()
    if not name:
        raise ValueError("trust owner name is required")
    try:
        pwd.getpwnam(name)
    except KeyError as e:
        raise ValueError(
            f"unix user {name!r} does not exist — create it first, e.g.\n"
            f"  sudo useradd -r -s /usr/sbin/nologin {name}"
        ) from e
    return name


def _chmod_tree(root: Path, *, dir_mode: int, file_mode: int) -> list[str]:
    actions: list[str] = []
    if not root.exists():
        return actions
    if root.is_file():
        os.chmod(root, file_mode)
        actions.append(f"chmod {file_mode:o} {root}")
        return actions
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        current = Path(dirpath)
        for name in filenames:
            path = current / name
            os.chmod(path, file_mode)
            actions.append(f"chmod {file_mode:o} {path}")
        for name in dirnames:
            path = current / name
            os.chmod(path, dir_mode)
            actions.append(f"chmod {dir_mode:o} {path}")
    os.chmod(root, dir_mode)
    actions.append(f"chmod {dir_mode:o} {root}")
    return actions


def _run_privileged(argv: list[str], *, dry_run: bool) -> None:
    if dry_run:
        return
    if os.geteuid() != 0:
        argv = ["sudo", *argv]
    proc = subprocess.run(argv, check=False, text=True, capture_output=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise PermissionError(detail or f"command failed: {' '.join(argv)}")


def apply_filesystem_hardening(owner: str, *, dry_run: bool = False) -> dict[str, Any]:
    """chown trust roots to ``owner`` and set world-readable, owner-writable modes."""
    trust_owner = resolve_trust_owner(owner)
    actions: list[str] = []
    for root in trust_root_directories():
        root = root.expanduser()
        if not root.exists() and not dry_run:
            root.mkdir(parents=True, exist_ok=True)
        target = str(root)
        actions.append(f"chown -R {trust_owner}:{trust_owner} {target}")
        _run_privileged(["chown", "-R", f"{trust_owner}:{trust_owner}", target], dry_run=dry_run)
        if not dry_run and root.exists():
            actions.extend(_chmod_tree(root, dir_mode=0o755, file_mode=0o644))
    return {"owner": trust_owner, "actions": actions, "dry_run": dry_run}


def harden_trust_root(
    *,
    owner: str = "",
    project_root: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Apply filesystem separation and wire strict trust root into MCP env."""
    before = audit_trust_root()
    fs = apply_filesystem_hardening(owner or default_trust_owner(), dry_run=dry_run)
    merged: list[str] = []
    if project_root is not None:
        for path in project_mcp_json_paths(project_root):
            if dry_run:
                if path.is_file():
                    merged.append(str(path))
            elif merge_mcp_env(path, mcp_env_snippet()):
                merged.append(str(path))
    after = audit_trust_root() if not dry_run else before
    return {
        "before": before,
        "after": after,
        "filesystem": fs,
        "mcp_json_updated": merged,
        "operator_commands": operator_command_hints(fs["owner"]),
    }


def operator_command_hints(owner: str) -> list[str]:
    cli = shutil.which("wmc") or shutil.which("willow-mcp") or "willow-mcp"
    prefix = f"sudo -u {owner} {cli}" if os.geteuid() != 0 else cli
    return [
        f"{prefix} grant-net <app_id> --ttl 30m --reason \"…\"",
        f"{prefix} consent set internet true",
        f"{prefix} revoke-net <app_id>",
        "Reload the IDE after MCP env changes.",
    ]
