"""Canonical $WILLOW_HOME path API for the willow-mcp standalone product.

All runtime filesystem layout is defined in docs/design/product-layout.md (LOCKED).
Import from here — do not scatter path joins across the codebase.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

LAYOUT_VERSION = 1

_DISPATCH_ID_RE = re.compile(r"^[A-Z0-9]{8}$")
_APP_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")
_PROJECT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,128}$")
_PACKAGE_NAME_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def willow_home() -> Path:
    return Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))


def layout_version_path() -> Path:
    return willow_home() / ".layout-version"


# ── config/ ───────────────────────────────────────────────────────────────────

def config_dir() -> Path:
    return willow_home() / "config"


def settings_global_path() -> Path:
    """Canonical settings; legacy root copy may still exist — see consent.py."""
    return config_dir() / "settings.global.json"


def settings_global_legacy_path() -> Path:
    return willow_home() / "settings.global.json"


def consent_path() -> Path:
    return config_dir() / "consent.json"


def consent_legacy_path() -> Path:
    return willow_home() / "consent.json"


def agent_roster_path() -> Path:
    return config_dir() / "agent_roster.json"


def persona_envelopes_path() -> Path:
    return config_dir() / "persona_envelopes.json"


def rotation_path() -> Path:
    return config_dir() / "rotation.json"


# ── dispatch / sessions / handoffs ────────────────────────────────────────────

def dispatch_root() -> Path:
    return willow_home() / "dispatch"


def dispatch_dir(dispatch_id: str) -> Path:
    if not _DISPATCH_ID_RE.match(dispatch_id or ""):
        raise ValueError(f"invalid dispatch_id: {dispatch_id!r}")
    return dispatch_root() / dispatch_id


def sessions_dir() -> Path:
    return willow_home() / "sessions"


def session_path(app_id: str, session_id: str) -> Path:
    if not _APP_ID_RE.match(app_id or ""):
        raise ValueError(f"invalid app_id: {app_id!r}")
    safe_sid = re.sub(r"[^a-zA-Z0-9_\-]", "_", session_id or "")[:64]
    return sessions_dir() / f"{app_id}-{safe_sid}.json"


def handoffs_dir(app_id: str = "") -> Path:
    base = willow_home() / "handoffs"
    if not app_id:
        return base
    if not _APP_ID_RE.match(app_id):
        raise ValueError(f"invalid app_id: {app_id!r}")
    return base / app_id


# ── projects / knowledge ──────────────────────────────────────────────────────

def projects_dir() -> Path:
    return willow_home() / "projects"


def project_path(project_id: str) -> Path:
    if not _PROJECT_ID_RE.match(project_id or ""):
        raise ValueError(f"invalid project_id: {project_id!r}")
    return projects_dir() / f"{project_id}.json"


def knowledge_dir() -> Path:
    return willow_home() / "knowledge"


def knowledge_atom_path(atom_id: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_\-]", "_", atom_id or "")[:128]
    if not safe:
        raise ValueError("invalid atom_id")
    return knowledge_dir() / f"{safe}.json"


# ── templates / skills / hooks / packages ───────────────────────────────────

def templates_dir() -> Path:
    return willow_home() / "templates"


def skills_dir() -> Path:
    return willow_home() / "skills"


def hooks_dir() -> Path:
    return willow_home() / "hooks"


def personas_dir() -> Path:
    return willow_home() / "personas"


def seeds_dir() -> Path:
    return willow_home() / "seeds"


def specialists_config_path() -> Path:
    return config_dir() / "specialists.json"


def packages_dir() -> Path:
    return willow_home() / "packages"


def package_dir(package_name: str) -> Path:
    if not _PACKAGE_NAME_RE.match(package_name or ""):
        raise ValueError(f"invalid package_name: {package_name!r}")
    return packages_dir() / package_name


# ── mcp_apps / store ──────────────────────────────────────────────────────────

def mcp_apps_root() -> Path:
    override = os.environ.get("WILLOW_MCP_APPS_ROOT", "").strip()
    if override:
        return Path(override)
    return willow_home() / "mcp_apps"


def mcp_app_dir(app_id: str) -> Path:
    if not _APP_ID_RE.match(app_id or ""):
        raise ValueError(f"invalid app_id: {app_id!r}")
    return mcp_apps_root() / app_id


def store_root() -> Path:
    override = os.environ.get("WILLOW_STORE_ROOT", "").strip()
    if override:
        return Path(override)
    return willow_home() / "store"


# ── ledgers / resources / constitutional / logs ───────────────────────────────

def ledgers_dir() -> Path:
    return willow_home() / "ledgers"


def ledger_entry_path(entry_hash: str) -> Path:
    safe = re.sub(r"[^a-fA-F0-9]", "", entry_hash or "")[:64]
    if not safe:
        raise ValueError("invalid entry_hash")
    return ledgers_dir() / "entries" / f"{safe}.json"


def resources_dir() -> Path:
    return willow_home() / "resources"


def constitutional_dir() -> Path:
    return willow_home() / "constitutional"


def review_queue_path() -> Path:
    return constitutional_dir() / "review_queue.json"


def logs_dir() -> Path:
    return willow_home() / "logs"


def log_path_for_date(date_str: str) -> Path:
    # YYYY-MM-DD
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", date_str or ""):
        raise ValueError(f"invalid date: {date_str!r}")
    return logs_dir() / f"{date_str}.log"


# ── internal (product runtime; not operator-facing tree docs) ─────────────────

def worker_heartbeat_dir() -> Path:
    return willow_home() / "worker_heartbeat"


def vault_db_path() -> Path:
    return willow_home() / "vault.db"


def mcp_token_path() -> Path:
    return willow_home() / "mcp_token.json"


def identity_bindings_dir() -> Path:
    return mcp_apps_root() / "_identity_bindings"


def net_leases_dir() -> Path:
    return mcp_apps_root() / "_net_leases"


def bundle_dir() -> Path:
    """Shipped seeds inside the installed package."""
    return Path(__file__).resolve().parent / "bundle"


def all_layout_dirs() -> list[Path]:
    """Directories created by willow-mcp-init (scaffold only)."""
    home = willow_home()
    return [
        home / "config",
        home / "dispatch",
        home / "handoffs",
        home / "sessions",
        home / "projects",
        home / "knowledge",
        home / "templates",
        home / "skills",
        home / "hooks",
        home / "personas",
        home / "seeds",
        home / "packages",
        home / "mcp_apps",
        home / "store",
        home / "ledgers" / "entries",
        home / "resources",
        home / "constitutional",
        home / "logs",
        home / "worker_heartbeat",
    ]


def new_dispatch_id() -> str:
    import uuid

    return uuid.uuid4().hex[:8].upper()
