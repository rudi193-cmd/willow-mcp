"""Load agent_seed_v1 from $WILLOW_HOME/seeds/{agent_id}.json.

AS-3: advisory load on session_enter; pending ratification surfaces gaps.
PGP verify when WILLOW_PGP_FINGERPRINT is set and status is ratified.

See docs/design/agent-seed.md.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .paths import seeds_dir, willow_home
from . import pgp

SEED_FORMAT = "agent_seed_v1"
_AGENT_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def seed_path(agent_id: str) -> Path | None:
    key = (agent_id or "").strip()
    if not _AGENT_ID_RE.match(key):
        return None
    return seeds_dir() / f"{key}.json"


def _seed_excerpt(data: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    seed_block = data.get("seed") or {}
    if seed_block.get("instruction"):
        out["instruction"] = seed_block["instruction"]
    persona = data.get("persona") or {}
    if persona.get("character"):
        out["character"] = persona["character"]
    context = data.get("context") or {}
    for key in ("cognitive_style", "correction_pattern", "active_work"):
        if context.get(key):
            out[key] = context[key]
    identity = data.get("identity") or {}
    if identity.get("kind"):
        out["kind"] = identity["kind"]
    return out


def load_agent_seed(agent_id: str, *, include_full: bool = False) -> dict[str, Any]:
    """Load seed file if present. Never raises — returns structured status."""
    path = seed_path(agent_id)
    if path is None:
        return {"present": False, "reason": "invalid_agent_id"}

    if not path.is_file():
        return {"present": False, "reason": "no_seed_file"}

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return {"present": False, "reason": f"unreadable: {e}"}

    if not isinstance(data, dict):
        return {"present": False, "reason": "seed must be a JSON object"}

    if data.get("format") != SEED_FORMAT:
        return {
            "present": False,
            "reason": f"unsupported format: {data.get('format')!r}",
        }

    rat = (data.get("seed") or {}).get("ratification") or {}
    status = str(rat.get("status") or "pending").lower()
    gaps = list(data.get("gaps") or [])

    advisory = None
    if status == "pending":
        advisory = (
            "Agent seed unratified — boot is advisory only; gaps surfaced; "
            "not eligible for KB canon promotion."
        )

    verify: dict[str, Any] | None = None
    if pgp.pgp_enabled():
        if status == "ratified":
            ok, reason = pgp.verify_detached(path)
            verify = {"ok": ok, "reason": reason}
        elif status == "pending":
            verify = {"ok": None, "reason": "skipped_pending_ratification"}
        else:
            verify = {"ok": False, "reason": f"unknown ratification status: {status}"}

    rel = str(path.relative_to(willow_home()))
    block: dict[str, Any] = {
        "present": True,
        "path": rel,
        "format": SEED_FORMAT,
        "ratification_status": status,
        "gaps": gaps,
        "advisory": advisory,
        "excerpt": _seed_excerpt(data),
    }
    if verify is not None:
        block["verify"] = verify
    if include_full:
        block["seed"] = data
    return block


def seed_context(agent_id: str) -> dict[str, Any]:
    """session_enter payload wrapper."""
    return {"agent_seed": load_agent_seed(agent_id)}
