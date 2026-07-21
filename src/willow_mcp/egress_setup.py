"""Operator-local egress key bootstrap and default path resolution.

Keys and this manifest intentionally live outside ``WILLOW_HOME`` / worker
sandboxes.  ``willow-mcp setup-egress`` creates or registers a keypair once;
``public_key_path()`` and ``sign-net-task`` resolve defaults from here so
operators are not hand-editing env vars on every install.
"""

from __future__ import annotations

import json
import os
import stat
from pathlib import Path

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

_MANIFEST = "manifest.json"
_DEFAULT_DIR = Path.home() / ".config" / "willow-mcp" / "egress"


def config_dir() -> Path:
    raw = os.environ.get("WILLOW_MCP_EGRESS_CONFIG_DIR", "").strip()
    return Path(raw).expanduser() if raw else _DEFAULT_DIR


def manifest_path() -> Path:
    return config_dir() / _MANIFEST


def default_private_key_path() -> Path:
    return config_dir() / "private.pem"


def default_public_key_path() -> Path:
    return config_dir() / "public.pem"


def _protected_roots() -> tuple[Path, Path]:
    return (
        Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow")).expanduser(),
        Path(os.environ.get("WILLOW_STORE_ROOT", Path.home() / ".willow")).expanduser(),
    )


def validate_key_path(path: Path) -> None:
    """Raise when a signing key is missing, world-readable, or inside a sandbox mount."""
    try:
        mode = stat.S_IMODE(path.stat().st_mode)
    except OSError as e:
        raise ValueError(f"cannot read signing key metadata: {e}") from e
    if mode & 0o077:
        raise ValueError("signing key must not be group/world accessible")
    resolved = path.resolve()
    for root in _protected_roots():
        if resolved == root.resolve() or root.resolve() in resolved.parents:
            raise ValueError(
                "signing key must live outside WILLOW_HOME/WILLOW_STORE_ROOT, "
                "which are mounted into worker sandboxes"
            )


def load_manifest() -> dict | None:
    path = manifest_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def save_manifest(*, private_key: Path, public_key: Path) -> dict:
    private_key = private_key.expanduser().resolve()
    public_key = public_key.expanduser().resolve()
    data = {
        "format": "willow-mcp-egress-v1",
        "private_key": str(private_key),
        "public_key": str(public_key),
    }
    config_dir().mkdir(parents=True, exist_ok=True)
    manifest_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return data


def resolve_private_key_path() -> Path | None:
    env = os.environ.get("WILLOW_MCP_EGRESS_SIGNING_KEY", "").strip()
    if env:
        return Path(env).expanduser()
    manifest = load_manifest()
    if manifest and manifest.get("private_key"):
        return Path(str(manifest["private_key"])).expanduser()
    candidate = default_private_key_path()
    return candidate if candidate.is_file() else None


def resolve_public_key_path() -> Path | None:
    env = os.environ.get("WILLOW_MCP_EGRESS_PUBLIC_KEY", "").strip()
    if env:
        return Path(env).expanduser()
    manifest = load_manifest()
    if manifest and manifest.get("public_key"):
        return Path(str(manifest["public_key"])).expanduser()
    candidate = default_public_key_path()
    return candidate if candidate.is_file() else None


def mcp_env_snippet() -> dict[str, str]:
    pub = resolve_public_key_path()
    if pub is None:
        return {}
    return {"WILLOW_MCP_EGRESS_PUBLIC_KEY": str(pub.resolve())}


def _generate_keypair(private_path: Path, public_path: Path) -> None:
    private_path.parent.mkdir(parents=True, exist_ok=True)
    private = Ed25519PrivateKey.generate()
    private_pem = private.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_pem = private.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    private_path.write_bytes(private_pem)
    public_path.write_bytes(public_pem)
    os.chmod(private_path, stat.S_IMODE(0o600))


def ensure_keypair(
    *,
    force: bool = False,
    private_key: Path | None = None,
    public_key: Path | None = None,
) -> dict:
    """Create or register an egress keypair. Idempotent unless ``force``."""
    if private_key and public_key:
        private_path = private_key.expanduser()
        public_path = public_key.expanduser()
        if not private_path.is_file() or not public_path.is_file():
            raise ValueError("both --private-key and --public-key must exist")
        validate_key_path(private_path)
        manifest = save_manifest(private_key=private_path, public_key=public_path)
        return {"action": "registered", **manifest}

    private_path = default_private_key_path()
    public_path = default_public_key_path()
    if private_path.is_file() and public_path.is_file() and not force:
        manifest = save_manifest(private_key=private_path, public_key=public_path)
        return {"action": "exists", **manifest}

    if force and private_path.exists():
        private_path.unlink()
    if force and public_path.exists():
        public_path.unlink()

    _generate_keypair(private_path, public_path)
    validate_key_path(private_path)
    manifest = save_manifest(private_key=private_path, public_key=public_path)
    return {"action": "created", **manifest}


def merge_mcp_env(path: Path, env: dict[str, str]) -> bool:
    """Merge ``env`` into ``mcpServers.willow-mcp.env`` when the file exists."""
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
    return [
        root / ".cursor" / "mcp.json",
        root / ".mcp.json",
    ]
