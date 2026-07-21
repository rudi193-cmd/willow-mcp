"""B-32: operator tooling to separate confirm authority from the agent process.

The agent may REQUEST egress; only the operator (via a uid the agent does not
share write access with) may CONFIRM it. ``harden-trust-root`` chowns policy
roots to ``willow-operator`` and restores MCP runtime write paths (``store/``,
``dispatch/``, …) to the runtime user.
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
_TRUST_DIR_NAMES = frozenset({"config", "mcp_apps"})


def default_trust_owner() -> str:
    return os.environ.get("WILLOW_MCP_TRUST_OWNER", "").strip() or DEFAULT_TRUST_OWNER


def default_runtime_user() -> str:
    explicit = os.environ.get("WILLOW_MCP_RUNTIME_USER", "").strip()
    if explicit:
        return explicit
    sudo_user = os.environ.get("SUDO_USER", "").strip()
    if sudo_user:
        return sudo_user
    return pwd.getpwuid(os.getuid()).pw_name


def trust_policy_files() -> list[Path]:
    """Legacy policy files that may live directly under $WILLOW_HOME (not whole-home chown)."""
    files: list[Path] = []
    for candidate in (
        paths.settings_global_legacy_path(),
        paths.consent_legacy_path(),
    ):
        if candidate.is_file():
            files.append(candidate)
    return files


def trust_root_directories() -> list[Path]:
    """Directories whose contents authorize egress or standing policy."""
    roots = [paths.mcp_apps_root(), paths.config_dir()]
    seen: set[str] = set()
    out: list[Path] = []
    for root in roots:
        key = str(root.resolve(strict=False))
        if key not in seen:
            seen.add(key)
            out.append(root)
    return out


def runtime_writable_directories() -> list[Path]:
    """Paths the MCP server must write during normal operation."""
    home = paths.willow_home()
    blocked = {str(paths.config_dir().resolve(strict=False)),
               str(paths.mcp_apps_root().resolve(strict=False))}
    out: list[Path] = []
    seen: set[str] = set()
    for directory in paths.all_layout_dirs():
        try:
            rel = directory.resolve(strict=False).relative_to(home.resolve(strict=False))
        except ValueError:
            rel = None
        if rel is not None and rel.parts and rel.parts[0] in _TRUST_DIR_NAMES:
            continue
        key = str(directory.resolve(strict=False))
        if key in seen or key in blocked:
            continue
        seen.add(key)
        out.append(directory)
    store = paths.store_root()
    store_key = str(store.resolve(strict=False))
    if store_key not in seen and store_key not in blocked:
        seen.add(store_key)
        out.append(store)
    return out


def runtime_writable_home_children() -> list[Path]:
    """Top-level $WILLOW_HOME entries (except trust dirs) when a prior chown swept too wide."""
    home = paths.willow_home()
    if not home.is_dir():
        return []
    children: list[Path] = []
    for entry in sorted(home.iterdir()):
        if entry.name in _TRUST_DIR_NAMES:
            continue
        children.append(entry)
    return children


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


def audit_store_writable() -> dict[str, Any]:
    root = paths.store_root()
    check: dict[str, Any] = {"root": str(root), "writable": False, "error": None}
    try:
        root.mkdir(parents=True, exist_ok=True)
        probe = root / ".diag_write_probe"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
        check["writable"] = True
    except OSError as e:
        check["error"] = str(e)
    return check


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
    store = audit_store_writable()
    return {
        "strict_trust_root": strict,
        "forgeable": all_forgeable,
        "hardened": strict and not all_forgeable,
        "trust_roots": [str(p) for p in trust_root_directories()],
        "trust_policy_files": [str(p) for p in trust_policy_files()],
        "runtime_paths": [str(p) for p in runtime_writable_directories()],
        "store": store,
        "trust_owner_hint": default_trust_owner(),
        "runtime_user_hint": default_runtime_user(),
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


def resolve_runtime_user(runtime_user: str) -> str:
    name = (runtime_user or default_runtime_user()).strip()
    if not name:
        raise ValueError("runtime user name is required")
    try:
        pwd.getpwnam(name)
    except KeyError as e:
        raise ValueError(f"unix user {name!r} does not exist") from e
    return name


def _chmod_tree(
    root: Path,
    *,
    dir_mode: int,
    file_mode: int,
    dry_run: bool = False,
) -> list[str]:
    """Set modes under ``root`` using the same privilege boundary as chown."""
    actions: list[str] = []
    if not root.exists():
        return actions
    file_mode_s = format(file_mode, "o")
    dir_mode_s = format(dir_mode, "o")
    target = str(root)
    if root.is_file():
        actions.append(f"chmod {file_mode_s} {target}")
        _run_privileged(["chmod", file_mode_s, target], dry_run=dry_run)
        return actions
    actions.append(f"find {target} -type f -exec chmod {file_mode_s} {{}} +")
    actions.append(f"find {target} -type d -exec chmod {dir_mode_s} {{}} +")
    _run_privileged(
        ["find", target, "-type", "f", "-exec", "chmod", file_mode_s, "{}", "+"],
        dry_run=dry_run,
    )
    _run_privileged(
        ["find", target, "-type", "d", "-exec", "chmod", dir_mode_s, "{}", "+"],
        dry_run=dry_run,
    )
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


def _chown_target(target: Path, owner: str, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    path = str(target)
    if target.is_file():
        actions.append(f"chown {owner}:{owner} {path}")
        _run_privileged(["chown", f"{owner}:{owner}", path], dry_run=dry_run)
        return actions
    actions.append(f"chown -R {owner}:{owner} {path}")
    _run_privileged(["chown", "-R", f"{owner}:{owner}", path], dry_run=dry_run)
    return actions


def apply_trust_root_hardening(owner: str, *, dry_run: bool = False) -> dict[str, Any]:
    """chown policy roots to ``owner`` with world-readable modes."""
    trust_owner = resolve_trust_owner(owner)
    actions: list[str] = []
    for root in trust_root_directories():
        root = root.expanduser()
        if not root.exists() and not dry_run:
            root.mkdir(parents=True, exist_ok=True)
        actions.extend(_chown_target(root, trust_owner, dry_run=dry_run))
        if root.exists():
            actions.extend(
                _chmod_tree(root, dir_mode=0o755, file_mode=0o644, dry_run=dry_run)
            )
    for policy_file in trust_policy_files():
        if policy_file.is_file() or dry_run:
            actions.extend(_chown_target(policy_file, trust_owner, dry_run=dry_run))
            if policy_file.is_file():
                actions.extend(
                    _chmod_tree(policy_file, dir_mode=0o755, file_mode=0o644, dry_run=dry_run)
                )
    return {"owner": trust_owner, "actions": actions, "dry_run": dry_run}


def repair_runtime_permissions(runtime_user: str = "", *, dry_run: bool = False) -> dict[str, Any]:
    """Restore MCP runtime write paths to the server user (store, dispatch, …)."""
    user = resolve_runtime_user(runtime_user)
    actions: list[str] = []
    targets: list[Path] = []
    seen: set[str] = set()
    for path in [*runtime_writable_directories(), *runtime_writable_home_children()]:
        key = str(path.resolve(strict=False))
        if key in seen:
            continue
        seen.add(key)
        targets.append(path)
    for target in targets:
        if not target.exists() and not dry_run:
            if target.suffix:
                target.parent.mkdir(parents=True, exist_ok=True)
            else:
                target.mkdir(parents=True, exist_ok=True)
        if target.exists() or dry_run:
            actions.extend(_chown_target(target, user, dry_run=dry_run))
            if target.exists() and target.is_dir():
                actions.extend(
                    _chmod_tree(target, dir_mode=0o755, file_mode=0o644, dry_run=dry_run)
                )
            elif target.exists() and target.is_file():
                actions.extend(
                    _chmod_tree(target, dir_mode=0o755, file_mode=0o644, dry_run=dry_run)
                )
    receipt = paths.willow_home() / "mcp_receipt.db"
    if receipt.exists() or dry_run:
        actions.extend(_chown_target(receipt, user, dry_run=dry_run))
    return {"runtime_user": user, "targets": [str(p) for p in targets], "actions": actions, "dry_run": dry_run}


def apply_filesystem_hardening(owner: str, *, dry_run: bool = False) -> dict[str, Any]:
    """Trust-root hardening plus runtime repair (backward-compatible name)."""
    trust = apply_trust_root_hardening(owner, dry_run=dry_run)
    runtime = repair_runtime_permissions(dry_run=dry_run)
    return {
        "owner": trust["owner"],
        "runtime_user": runtime["runtime_user"],
        "actions": trust["actions"] + runtime["actions"],
        "dry_run": dry_run,
        "trust": trust,
        "runtime": runtime,
    }


def harden_trust_root(
    *,
    owner: str = "",
    runtime_user: str = "",
    project_root: Path | None = None,
    dry_run: bool = False,
    repair_runtime: bool = True,
) -> dict[str, Any]:
    """Apply filesystem separation and wire strict trust root into MCP env."""
    before = audit_trust_root()
    trust = apply_trust_root_hardening(owner or default_trust_owner(), dry_run=dry_run)
    runtime = (
        repair_runtime_permissions(runtime_user, dry_run=dry_run)
        if repair_runtime
        else {
            "runtime_user": default_runtime_user(),
            "actions": [],
            "dry_run": dry_run,
            "targets": [],
        }
    )
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
        "filesystem": {
            "owner": trust["owner"],
            "runtime_user": runtime["runtime_user"],
            "actions": trust["actions"] + runtime["actions"],
            "dry_run": dry_run,
            "trust": trust,
            "runtime": runtime,
        },
        "mcp_json_updated": merged,
        "operator_commands": operator_command_hints(trust["owner"]),
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
