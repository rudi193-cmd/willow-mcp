"""Federated MCP: server discovery, spec parsing, and the ratified registry.

willow-mcp has always been a server. This is the substrate for it to also be a
*client* — calling tools on other, independently-launched MCP servers spread
through the fleet. Build order and every decision below follow
docs/design/federated-mcp-gating.md, written and merged (#284) before any of
this existed, precisely so the gate would not be retrofitted onto code that
already assumed it away.

Two things live here, kept apart on purpose:

  Discovery   — read-only inventory. Walk the filesystem for `.mcp.json`
                files and report which ones the ratified registry does not
                yet own. Never spawns anything, never grants anything.
  Ratification — the operator act that promotes a discovered server spec into
                something `mcp_federation_client` may connect to. Writing a
                `.mcp.json` lives in repositories an agent can write; if that
                alone were enough to connect, an agent would be minting its
                own capability by editing a file (the same #183 kill chain
                `gate._load_manifest` reasons about, arriving through a
                different path). So: discovery is inventory only, and
                connecting requires an entry an operator explicitly ratified
                under this module's own `0700` directory.

`_stable_id()` is the identity a namespaced permission (`gate.
federated_tool_permission`) and an egress lease are keyed on — a digest of the
server's *launch* identity (command + args + resolved binary path), not its
human label, so renaming a server in a config file never silently carries its
grants over to a different program.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from . import paths, pgp

logger = logging.getLogger("willow_mcp.mcp_federation")

#: Directories a discovery walk never descends into: version control, build
#: output, dependency caches, and (deliberately) willow-mcp's own runtime
#: state. Mirrors the reasoning `_leases_root`/`identity_bindings_dir` already
#: apply elsewhere — state directories are not "servers to discover", they are
#: this process's own bookkeeping.
_SKIP_DIR_NAMES = frozenset({
    ".git", "node_modules", "__pycache__", ".venv", "venv", ".tox",
    "dist", "build", ".mypy_cache", ".pytest_cache", ".ruff_cache",
    ".willow",
})


def _skip_scan_path(path: Path) -> bool:
    """True if any path component names a directory a scan should not enter.

    Checked against every ancestor component, not just the leaf, so a
    `.mcp.json` sitting three levels under `node_modules/` is skipped exactly
    like one sitting directly inside it.
    """
    return any(part in _SKIP_DIR_NAMES for part in path.parts)


def discover_mcp_json_files(root: Path) -> list[Path]:
    """Every `.mcp.json` under `root`, minus the skip list. Read-only; never
    parses, never connects. The first question an orchestrator must answer —
    "which MCP servers exist that willow-mcp does not know about" — starts
    here."""
    root = Path(root)
    if not root.is_dir():
        return []
    return sorted(
        p for p in root.rglob(".mcp.json")
        if p.is_file() and not _skip_scan_path(p.relative_to(root))
    )


def _resolved_command_path(command: str) -> str:
    """Best-effort absolute resolution of a launch command, for `_stable_id`.

    Falls back to the raw string when the command is not found on PATH (a
    template var like `${HOME}/...` before expansion, or a binary not
    installed on *this* host) — identity is still stable across runs on the
    same host, which is all `_stable_id` needs; it is not a claim that the
    command is runnable.
    """
    found = shutil.which(command)
    if found:
        return str(Path(found).resolve())
    try:
        return str(Path(command).expanduser().resolve(strict=False))
    except OSError:
        return command


def _stable_id(resolved_path: str, name: str) -> str:
    """`sha256(resolved_path + "::" + name)[:12]` — the server's identity.

    Digests the *launch* identity plus the config's own name for it, not a
    human label alone: two servers named "fs" in two different `.mcp.json`
    files that run different binaries must never collide, and the same
    binary renamed in a config file must not silently keep its old grants.
    """
    payload = f"{resolved_path}::{name}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:12]


@dataclass(frozen=True)
class McpServerSpec:
    """One downstream MCP server, as read from a `.mcp.json` (or `servers`)
    entry. Frozen: a spec is a fact about what was on disk at parse time, not
    something a caller mutates in place.
    """

    id: str
    name: str
    command: str
    args: tuple[str, ...] = field(default_factory=tuple)
    #: Environment variable NAMES this server receives — never values, and
    #: never `os.environ` inherited wholesale. Decision 4(a): a server spec
    #: names the keys it receives; anything unnamed is absent, not empty.
    #: `WILLOW_PGP_FINGERPRINT` / `WILLOW_MCP_API_KEY` / `PGPASSWORD` are the
    #: concrete keys the design doc names as the trust root a blanket
    #: `env=os.environ.copy()` would hand a child.
    env_keys: tuple[str, ...] = field(default_factory=tuple)
    cwd: Optional[str] = None
    transport: str = "stdio"
    url: Optional[str] = None
    source_path: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id, "name": self.name, "command": self.command,
            "args": list(self.args), "env_keys": list(self.env_keys),
            "cwd": self.cwd, "transport": self.transport, "url": self.url,
            "source_path": self.source_path,
        }

    @staticmethod
    def from_dict(data: dict[str, Any]) -> "McpServerSpec":
        return McpServerSpec(
            id=str(data["id"]), name=str(data["name"]), command=str(data.get("command", "")),
            args=tuple(str(a) for a in (data.get("args") or [])),
            env_keys=tuple(str(k) for k in (data.get("env_keys") or [])),
            cwd=data.get("cwd"), transport=str(data.get("transport") or "stdio"),
            url=data.get("url"), source_path=str(data.get("source_path", "")),
        )


def _entries_block(raw: dict[str, Any]) -> dict[str, Any]:
    """`.mcp.json` names its server map `mcpServers` (Claude convention) or
    `servers` (VS Code / others) — accept either, preferring `mcpServers` when
    a file somehow has both."""
    block = raw.get("mcpServers")
    if isinstance(block, dict):
        return block
    block = raw.get("servers")
    if isinstance(block, dict):
        return block
    return {}


def parse_mcp_json(path: Path) -> list[McpServerSpec]:
    """Parse one `.mcp.json` into specs. Never raises on a malformed file or a
    malformed individual entry — logs and skips, so one bad entry cannot hide
    the rest of a file's servers from discovery."""
    path = Path(path)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning("mcp_federation: %s is unparseable (%s) — skipped", path, e)
        return []
    if not isinstance(raw, dict):
        return []

    specs: list[McpServerSpec] = []
    for name, entry in _entries_block(raw).items():
        if not isinstance(name, str) or not isinstance(entry, dict):
            continue
        # `type`/`transport` both name the same field across config dialects.
        transport = str(entry.get("transport") or entry.get("type") or "stdio")
        command = str(entry.get("command") or "")
        if transport == "stdio" and not command:
            logger.warning("mcp_federation: %s entry %r has no command — skipped", path, name)
            continue
        resolved = _resolved_command_path(command) if command else str(entry.get("url") or name)
        env = entry.get("env")
        env_keys = tuple(sorted(env.keys())) if isinstance(env, dict) else ()
        specs.append(McpServerSpec(
            id=_stable_id(resolved, name),
            name=name,
            command=command,
            args=tuple(str(a) for a in (entry.get("args") or [])),
            env_keys=env_keys,
            cwd=entry.get("cwd"),
            transport=transport,
            url=entry.get("url"),
            source_path=str(path),
        ))
    return specs


def discover_all_specs(root: Path) -> list[McpServerSpec]:
    """Parse every discovered `.mcp.json` under `root` into specs."""
    specs: list[McpServerSpec] = []
    for p in discover_mcp_json_files(root):
        specs.extend(parse_mcp_json(p))
    return specs


# ── The ratified registry ──────────────────────────────────────────────────
#
# Lives beside `_net_leases/` and `_identity_bindings/` under `mcp_apps/` —
# the same reserved, operator-owned subtree, for the same reason: on a
# hardened install (B-32, `WILLOW_MCP_STRICT_TRUST_ROOT`) that directory is
# not writable by the uid the agent runs as, so ratifying a server is a host
# act, never something an in-session tool call can do to itself.

def federation_dir() -> Path:
    return paths.mcp_apps_root() / "_federation"


def registry_path() -> Path:
    return federation_dir() / "servers.json"


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(data, indent=2, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)


def _read_registry_file() -> tuple[dict[str, dict], bool]:
    """`(entries_by_id, signature_ok)`. `signature_ok` is always True when PGP
    enforcement is off (`WILLOW_PGP_FINGERPRINT` unset — file-system trust,
    same default as manifests); when it is on, a missing/invalid detached
    signature makes every entry unreadable, exactly like an unsigned manifest
    is treated as absent rather than partially trusted.
    """
    path = registry_path()
    if not path.is_file():
        return {}, True
    if pgp.pgp_enabled():
        ok, reason = pgp.verify_detached(path)
        if not ok:
            logger.error("mcp_federation: registry signature invalid (%s) — "
                         "treating as no ratified servers", reason)
            return {}, False
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logger.error("mcp_federation: registry unparseable (%s) — denying all", e)
        return {}, False
    if not isinstance(data, dict) or not isinstance(data.get("servers"), dict):
        return {}, False
    return data["servers"], True


def list_ratified() -> list[dict[str, Any]]:
    """Every ratified server entry, newest-ratified first. `[]` on a missing,
    corrupt, or (when PGP is enforced) unsigned/tampered registry — fail
    closed, in the spirit of `lease.read_lease` and `consent.read_consent`."""
    entries, ok = _read_registry_file()
    if not ok:
        return []
    return sorted(entries.values(), key=lambda e: e.get("ratified_at", ""), reverse=True)


def get_ratified(server_id: str) -> Optional[dict[str, Any]]:
    entries, ok = _read_registry_file()
    if not ok:
        return None
    return entries.get(server_id)


def is_ratified(server_id: str) -> bool:
    """The operator-side ceiling of Decision 2's intersection: True only when
    this server_id has a positively-read, (if enforced) signature-valid entry.
    A caller's manifest grant is the other half — neither is sufficient alone."""
    return get_ratified(server_id) is not None


def ratify(spec: McpServerSpec, *, ratified_by: str, reason: str = "") -> dict[str, Any]:
    """Promote a discovered spec into the ratified registry. **Operator-only —
    never call this from an MCP tool.** Mirrors `lease.grant`: not reachable
    through the gate, attributed, and it is the act `federation_egress`'s
    ceiling check depends on. Re-ratifying an existing id overwrites it (an
    operator updating env_keys or command is how a spec is corrected), and the
    write is detach-signed when PGP enforcement is configured, the same way
    the signing seed is (`pgp.sign_detached`).
    """
    if not ratified_by:
        raise ValueError("ratified_by is required — an unattributed ratification is not one")
    entries, _ok = _read_registry_file()
    now = datetime.now(timezone.utc).isoformat()
    entries = dict(entries)
    entries[spec.id] = {
        **spec.to_dict(),
        "ratified_by": ratified_by,
        "ratified_at": now,
        "reason": reason,
    }
    path = registry_path()
    _write_json_atomic(path, {"servers": entries})
    if pgp.pgp_enabled():
        signed, detail = pgp.sign_detached(path)
        if not signed:
            logger.error("mcp_federation: ratification written but signing failed: %s", detail)
    logger.warning("mcp_federation: ratified server %r (%s) by %r: %s",
                   spec.name, spec.id, ratified_by, reason or "no reason given")
    return entries[spec.id]


def revoke_ratification(server_id: str) -> bool:
    """Remove a server from the ratified registry. **Operator-only.** True if
    an entry was there to remove."""
    entries, _ok = _read_registry_file()
    if server_id not in entries:
        return False
    entries = dict(entries)
    del entries[server_id]
    path = registry_path()
    _write_json_atomic(path, {"servers": entries})
    if pgp.pgp_enabled():
        pgp.sign_detached(path)
    logger.warning("mcp_federation: revoked ratification for server %r", server_id)
    return True


def _managed_source_paths() -> set[str]:
    """The `.mcp.json` paths the ratified registry already draws entries
    from — "what the registry owns", the subtrahend in the shadow-IT scan
    below."""
    return {e.get("source_path", "") for e in list_ratified() if e.get("source_path")}


def unregistered_mcp_files(root: Path) -> list[Path]:
    """Discovered `.mcp.json` files minus the ones the ratified registry
    already draws from — the shadow-IT detector. Inventory only: it never
    parses these into connectable specs and never ratifies anything; it
    answers "what exists that willow-mcp does not yet know about", which an
    operator then reviews and, if warranted, ratifies by hand.
    """
    managed = _managed_source_paths()
    return [p for p in discover_mcp_json_files(root) if str(p) not in managed]


def load_server_env(entry: dict[str, Any]) -> dict[str, str]:
    """The environment a downstream server subprocess receives: exactly the
    named `env_keys`, read from *this* process's environment at spawn time,
    and nothing else. Decision 4(a) — inherit nothing by default. A key named
    in `env_keys` that is unset here is simply absent from the child's
    environment, not empty-stringed: a spec cannot manufacture a credential
    this process was never given.
    """
    keys = entry.get("env_keys") or []
    return {k: os.environ[k] for k in keys if isinstance(k, str) and k in os.environ}
