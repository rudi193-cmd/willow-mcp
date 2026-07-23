"""AS-8: exposure membrane — standing defaults + per-destination slice resolution.

Config: $WILLOW_HOME/config/exposure.json (exposure_v1).
See docs/design/agent-seed.md §5.
"""

from __future__ import annotations

import json
from typing import Any

from .paths import exposure_config_path, willow_home
from .seed_loader import load_seed_document, seed_path

EXPOSURE_FORMAT = "exposure_v1"

# Preset → dotted field paths (checkbox IDs for future UI picker).
PRESET_FIELDS: dict[str, tuple[str, ...]] = {
    # The narrowest destination — exposes NOTHING. Registered for egress sinks
    # like Sentry telemetry, where the correct answer is "leak nothing at all"
    # (see observability.py). apply_field_paths([]) yields an empty body.
    "telemetry": (),
    "voice_only": ("persona.register", "persona.voice_rules"),
    "work_context": (
        "persona.register",
        "persona.voice_rules",
        "context.active_work",
        "context.session_pattern",
        "context.correction_pattern",
    ),
    "full_seed": (
        "persona.register",
        "persona.voice_rules",
        "persona.character",
        "persona.pillars",
        "persona.cast",
        "context.active_work",
        "context.session_pattern",
        "context.correction_pattern",
        "context.cognitive_style",
        "context.personal_note",
        "seed.instruction",
    ),
}

SLICE_PRESETS = frozenset({"voice_only", "work_context", "full", "full_seed", "custom"})
_FULL_PRESETS = frozenset({"full", "full_seed"})
_OPERATOR_KIND = "operator"


def default_exposure_config() -> dict[str, Any]:
    return {
        "format": EXPOSURE_FORMAT,
        "defaults": {
            "session_enter": "work_context",
            "kb_ingest": "work_context",
            "agent_seed_mirror": "work_context",
            "grove": "voice_only",
            "cloud_llm": "voice_only",
            "sentry": "telemetry",
            "dispatch": "work_context",
            "*": "voice_only",
        },
        "agents": {
            "sean": {
                "defaults": {"kb_ingest": "voice_only", "cloud_llm": "voice_only"},
                "deny_presets": ["full_seed", "full"],
            }
        },
    }


def load_exposure_config() -> dict[str, Any]:
    path = exposure_config_path()
    if not path.is_file():
        return default_exposure_config()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default_exposure_config()
    if not isinstance(data, dict):
        return default_exposure_config()
    if data.get("format") != EXPOSURE_FORMAT:
        data = {**default_exposure_config(), **data, "format": EXPOSURE_FORMAT}
    return data


def _normalize_preset(name: str) -> str:
    key = (name or "").strip().lower()
    if key == "full":
        return "full_seed"
    return key


def _get_nested(data: dict[str, Any], path: str) -> Any:
    cur: Any = data
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


def _set_nested(body: dict[str, Any], path: str, value: Any) -> None:
    parts = path.split(".")
    cur = body
    for part in parts[:-1]:
        nxt = cur.get(part)
        if not isinstance(nxt, dict):
            nxt = {}
            cur[part] = nxt
        cur = nxt
    cur[parts[-1]] = value


def apply_field_paths(data: dict[str, Any], paths: list[str]) -> dict[str, Any]:
    body: dict[str, Any] = {}
    for path in paths:
        val = _get_nested(data, path)
        if val is not None and val != "" and val != [] and val != {}:
            _set_nested(body, path, val)
    return body


def apply_slice(data: dict[str, Any], slice_name: str) -> dict[str, Any]:
    """Apply a named exposure preset to seed JSON (backward-compatible with AS-5/6)."""
    preset = _normalize_preset(slice_name)
    if preset in _FULL_PRESETS:
        return dict(data)
    fields = PRESET_FIELDS.get(preset)
    if fields is None:
        raise ValueError(f"unsupported slice: {slice_name!r}")
    return apply_field_paths(data, list(fields))


def resolve_preset(agent_id: str, destination: str) -> tuple[str, str]:
    """Return (preset, source) where source is config path key used."""
    cfg = load_exposure_config()
    dest = (destination or "*").strip() or "*"
    agent_key = (agent_id or "").strip().lower()
    agents = cfg.get("agents") or {}
    agent_cfg = agents.get(agent_key) if isinstance(agents, dict) else None
    if isinstance(agent_cfg, dict):
        per_agent = agent_cfg.get("defaults") or {}
        if isinstance(per_agent, dict) and dest in per_agent:
            return _normalize_preset(str(per_agent[dest])), f"agents.{agent_key}.defaults.{dest}"
    defaults = cfg.get("defaults") or {}
    if isinstance(defaults, dict) and dest in defaults:
        return _normalize_preset(str(defaults[dest])), f"defaults.{dest}"
    if isinstance(defaults, dict) and "*" in defaults:
        return _normalize_preset(str(defaults["*"])), "defaults.*"
    return "voice_only", "builtin"


def preset_denied(agent_id: str, preset: str) -> str | None:
    cfg = load_exposure_config()
    agent_key = (agent_id or "").strip().lower()
    agents = cfg.get("agents") or {}
    agent_cfg = agents.get(agent_key) if isinstance(agents, dict) else None
    norm = _normalize_preset(preset)
    if isinstance(agent_cfg, dict):
        denied = { _normalize_preset(str(x)) for x in (agent_cfg.get("deny_presets") or []) }
        if norm in denied:
            return f"preset {norm!r} denied for agent {agent_key}"
    data, _ = load_seed_document(agent_id)
    if data and norm in _FULL_PRESETS:
        kind = str((data.get("identity") or {}).get("kind") or "").lower()
        if kind == _OPERATOR_KIND:
            return f"full_seed denied for operator kind"
    return None


def build_exposure_slice(
    agent_id: str,
    *,
    destination: str = "session_enter",
    preset: str = "",
    fields: list[str] | None = None,
) -> dict[str, Any]:
    """Resolve and apply exposure slice for outbound/session use."""
    key = (agent_id or "").strip()
    if seed_path(key) is None:
        return {"ok": False, "error": "invalid_agent_id", "agent_id": key}

    data, err = load_seed_document(key)
    if err or data is None:
        return {"ok": False, "error": err or "unreadable", "agent_id": key}

    if fields:
        chosen_preset = "custom"
        source = "fields_argument"
        field_list = [str(f).strip() for f in fields if str(f).strip()]
        body = apply_field_paths(data, field_list)
    else:
        chosen_preset, source = resolve_preset(key, destination) if not preset else (_normalize_preset(preset), "preset_argument")
        deny = preset_denied(key, chosen_preset)
        if deny:
            return {"ok": False, "error": "preset_denied", "reason": deny, "agent_id": key, "preset": chosen_preset}
        if chosen_preset == "custom":
            return {"ok": False, "error": "custom_requires_fields", "agent_id": key}
        if chosen_preset in _FULL_PRESETS:
            body = dict(data)
            field_list = list(PRESET_FIELDS["full_seed"])
        else:
            field_list = list(PRESET_FIELDS.get(chosen_preset, PRESET_FIELDS["voice_only"]))
            body = apply_field_paths(data, field_list)

    rel_cfg = str(exposure_config_path().relative_to(willow_home())) if exposure_config_path().is_file() else None
    return {
        "ok": True,
        "agent_id": key,
        "destination": destination,
        "preset": chosen_preset,
        "resolved_from": source,
        "config_path": rel_cfg,
        "fields": field_list,
        "body": body,
    }
