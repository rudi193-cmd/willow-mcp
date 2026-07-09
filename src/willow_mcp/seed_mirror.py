"""AS-5: mirror canonical home seeds into SOIL store collection.

Design collection name: agents/seeds — standalone store uses flat
`willow_agents_seeds` (matches orchestrator store_scope `willow_*`).
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .paths import willow_home
from .seed_loader import SEED_FORMAT, load_agent_seed, load_seed_document, seed_trusted

# Flat SOIL collection mirroring docs/design/agent-seed.md § agents/seeds
MIRROR_COLLECTION = "willow_agents_seeds"

SLICE_PRESETS = frozenset({"full", "voice_only", "work_context"})


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def apply_slice(data: dict[str, Any], slice_name: str) -> dict[str, Any]:
    """Return a seed excerpt for mirror/KB promotion presets."""
    if slice_name == "full":
        return data

    persona = data.get("persona") or {}
    context = data.get("context") or {}

    if slice_name == "voice_only":
        body: dict[str, Any] = {}
        if persona.get("register"):
            body.setdefault("persona", {})["register"] = persona["register"]
        if persona.get("voice_rules"):
            body.setdefault("persona", {})["voice_rules"] = persona["voice_rules"]
        return body

    if slice_name == "work_context":
        body = apply_slice(data, "voice_only")
        for key in ("active_work", "session_pattern"):
            if context.get(key):
                body.setdefault("context", {})[key] = context[key]
        if context.get("correction_pattern"):
            body.setdefault("context", {})["correction_pattern"] = context["correction_pattern"]
        return body

    raise ValueError(f"unsupported slice: {slice_name!r}")


def build_mirror_record(agent_id: str, *, slice_name: str = "full") -> dict[str, Any]:
    """Build mirror payload from home canonical seed (does not write store)."""
    key = (agent_id or "").strip()
    if slice_name not in SLICE_PRESETS:
        return {"ok": False, "error": f"unsupported slice: {slice_name}", "allowed": sorted(SLICE_PRESETS)}

    loaded = load_agent_seed(key)
    if not loaded.get("present"):
        return {"ok": False, "error": loaded.get("reason", "no_seed"), "agent_id": key}

    status = str(loaded.get("ratification_status") or "pending")
    if status != "ratified":
        return {
            "ok": False,
            "error": "seed_not_ratified",
            "agent_id": key,
            "ratification_status": status,
            "advisory": loaded.get("advisory"),
        }

    if not seed_trusted(loaded):
        return {
            "ok": False,
            "error": "seed_signature_invalid",
            "agent_id": key,
            "verify": loaded.get("verify"),
        }

    data, err = load_seed_document(key)
    if err or data is None:
        return {"ok": False, "error": err or "unreadable", "agent_id": key}

    rel = f"seeds/{key}.json"
    record: dict[str, Any] = {
        "format": SEED_FORMAT,
        "agent_id": key,
        "_mirror_of": rel,
        "_slice": slice_name,
        "_mirrored_at": _utc_now(),
        "ratification": (data.get("seed") or {}).get("ratification") or {},
        "body": apply_slice(data, slice_name),
    }
    if loaded.get("verify") is not None:
        record["verify"] = loaded["verify"]
    return {"ok": True, "agent_id": key, "collection": MIRROR_COLLECTION, "record": record}


def mirror_seed_to_store(store: Any, agent_id: str, *, slice_name: str = "full") -> dict[str, Any]:
    """Write mirror record to SOIL; record_id = {agent_id} or {agent_id}__{slice}."""
    built = build_mirror_record(agent_id, slice_name=slice_name)
    if not built.get("ok"):
        return built

    key = built["agent_id"]
    record = built["record"]
    rid = key if slice_name == "full" else f"{key}__{slice_name}"
    stored_id, action = store.put(MIRROR_COLLECTION, record, record_id=rid)
    return {
        "ok": True,
        "agent_id": key,
        "collection": MIRROR_COLLECTION,
        "record_id": stored_id,
        "action": action,
        "slice": slice_name,
        "_mirror_of": record["_mirror_of"],
    }
