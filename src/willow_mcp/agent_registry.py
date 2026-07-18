"""agent_registry — the operator-side keystore binding an agent identity to a
shared HMAC secret and a trust ceiling (willow-gate seam, decision D2).

Layout (outside mcp_apps/ so no store/list tool can enumerate it; the whole
`gate/` dir is 0700 and on the PreToolUse guard's owned side — a keystore,
guarded like one):

    $WILLOW_HOME/gate/registry.json          {agent_id: {"max_trust": int}}
    $WILLOW_HOME/gate/secrets/<agent_id>.key  32 random bytes, 0600, atomic

The ceiling registry stays readable/auditable; secret material sits in per-agent
0600 files. This is CLI/operator-only — no MCP tool may register, rotate, read, or
revoke a secret (the sudo invariant: an agent may request standing, never mint
it). See docs/design/willow-gate-seam.md §D2.
"""
from __future__ import annotations

import json
import os
import re
import secrets as _secrets
from pathlib import Path
from typing import Optional

from . import paths

_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def _gate_dir() -> Path:
    d = paths.willow_home() / "gate"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _registry_path() -> Path:
    return _gate_dir() / "registry.json"


def _secrets_dir() -> Path:
    d = _gate_dir() / "secrets"
    d.mkdir(parents=True, exist_ok=True)
    try:
        os.chmod(d, 0o700)
    except OSError:
        pass
    return d


def _validate_id(agent_id: str) -> str:
    if not agent_id or not _ID_RE.match(agent_id):
        raise ValueError(f"invalid agent_id: {agent_id!r}")
    return agent_id


def _read_registry() -> dict:
    p = _registry_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_registry(reg: dict) -> None:
    p = _registry_path()
    tmp = p.with_suffix(f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(reg, indent=2, sort_keys=True))
    os.replace(tmp, p)


def register_agent(agent_id: str, max_trust: int, secret: Optional[bytes] = None) -> dict:
    """Bind `agent_id` to a 32-byte secret and a MAX trust ceiling (0..4).
    Operator/CLI-only. Returns the secret hex ONCE so the operator can install it
    into the agent's client-side signer (the same secret verifies here and signs
    there — symmetric, per D2). Re-registering rotates the secret."""
    _validate_id(agent_id)
    if not isinstance(max_trust, int) or not 0 <= max_trust <= 4:
        raise ValueError("max_trust must be an int in 0..4")
    secret = secret if secret is not None else _secrets.token_bytes(32)
    if len(secret) < 32:
        raise ValueError("secret must be >= 32 bytes")
    key_path = _secrets_dir() / f"{agent_id}.key"
    tmp = key_path.with_suffix(f".tmp-{os.getpid()}")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        os.write(fd, secret)
    finally:
        os.close(fd)
    os.replace(tmp, key_path)
    reg = _read_registry()
    reg[agent_id] = {"max_trust": max_trust}
    _write_registry(reg)
    return {"agent_id": agent_id, "max_trust": max_trust, "secret_hex": secret.hex()}


def load(agent_id: str) -> Optional[tuple[bytes, int]]:
    """(secret, max_trust) for a registered agent, else None. The one reader the
    binder uses; never exposed through an MCP tool."""
    try:
        _validate_id(agent_id)
    except ValueError:
        return None
    reg = _read_registry()
    rec = reg.get(agent_id)
    if not isinstance(rec, dict) or "max_trust" not in rec:
        return None
    key_path = _secrets_dir() / f"{agent_id}.key"
    try:
        secret = key_path.read_bytes()
    except OSError:
        return None
    if not secret:
        return None
    return secret, int(rec["max_trust"])


def list_agents() -> dict:
    """{agent_id: max_trust} — auditable, no secret material."""
    return {a: r.get("max_trust") for a, r in _read_registry().items() if isinstance(r, dict)}


def revoke(agent_id: str) -> bool:
    """Remove an agent's secret + registry entry. Operator/CLI-only."""
    _validate_id(agent_id)
    reg = _read_registry()
    had = agent_id in reg
    reg.pop(agent_id, None)
    _write_registry(reg)
    try:
        (_secrets_dir() / f"{agent_id}.key").unlink()
    except OSError:
        pass
    return had
