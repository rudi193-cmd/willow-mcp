"""Load agent_seed_v1 from $WILLOW_HOME/seeds/{agent_id}.json.

AS-3: advisory load on session_enter; pending ratification surfaces gaps.
AS-4: PGP verify when WILLOW_PGP_FINGERPRINT is set; ratified + bad sig → untrusted.

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


def load_seed_document(agent_id: str) -> tuple[dict[str, Any] | None, str | None]:
    """Read and validate seed JSON from home. Returns (data, error_reason)."""
    path = seed_path(agent_id)
    if path is None:
        return None, "invalid_agent_id"
    if not path.is_file():
        return None, "no_seed_file"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        return None, f"unreadable: {e}"
    if not isinstance(data, dict):
        return None, "seed must be a JSON object"
    if data.get("format") != SEED_FORMAT:
        return None, f"unsupported format: {data.get('format')!r}"
    return data, None


def seed_trusted(loaded: dict[str, Any]) -> bool:
    """True when a ratified seed may promote/mirror (PGP enforced when enabled)."""
    if not loaded.get("present"):
        return False
    if str(loaded.get("ratification_status") or "").lower() != "ratified":
        return False
    trusted = loaded.get("trusted")
    if trusted is not None:
        return bool(trusted)
    return True


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
    data, err = load_seed_document(agent_id)
    if err:
        reason = err
        if err == "invalid_agent_id":
            return {"present": False, "reason": reason}
        if err == "no_seed_file":
            return {"present": False, "reason": reason}
        return {"present": False, "reason": reason}

    assert data is not None
    path = seed_path(agent_id)
    assert path is not None

    rat = (data.get("seed") or {}).get("ratification") or {}
    status = str(rat.get("status") or "pending").lower()
    gaps = list(data.get("gaps") or [])

    advisory = None
    if status == "pending":
        advisory = (
            "Agent seed unratified — boot is advisory only; gaps surfaced; "
            "not eligible for KB canon promotion or SOIL mirror."
        )

    verify: dict[str, Any] | None = None
    trusted: bool | None = None
    if pgp.pgp_enabled():
        if status == "ratified":
            ok, reason = pgp.verify_detached(path)
            verify = {"ok": ok, "reason": reason}
            trusted = ok
            if not ok:
                advisory = (
                    "Ratified seed failed PGP verification — treat as untrusted; "
                    "mirror and KB promotion denied until re-signed."
                )
        elif status == "pending":
            verify = {"ok": None, "reason": "skipped_pending_ratification"}
            trusted = False
        else:
            verify = {"ok": False, "reason": f"unknown ratification status: {status}"}
            trusted = False
    elif status == "ratified":
        trusted = True

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
    if trusted is not None:
        block["trusted"] = trusted
    if verify is not None:
        block["verify"] = verify
    if include_full:
        block["seed"] = data
    return block


def seed_context(agent_id: str) -> dict[str, Any]:
    """session_enter payload wrapper."""
    return {"agent_seed": load_agent_seed(agent_id)}
