"""AS-7: compile agent_seed_v1 persona block → $WILLOW_HOME/personas/{id}.md.

Registry supplies job / not_job / namespace when present; seed supplies voice.
See docs/design/agent-seed.md.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .paths import personas_dir, willow_home
from .registry import specialist_row
from .seed_loader import load_seed_document, seed_path

DEFAULT_CHECKSUM = "ΔΣ=42"


def render_persona_markdown(
    agent_id: str,
    data: dict[str, Any],
    *,
    registry_row: dict[str, Any] | None = None,
) -> str:
    """Render bundle-style persona .md from seed + optional registry row."""
    identity = data.get("identity") or {}
    persona = data.get("persona") or {}
    seed_block = data.get("seed") or {}
    row = registry_row if registry_row is not None else specialist_row(agent_id)
    row = row or {}

    display = str(identity.get("display_name") or row.get("display_name") or agent_id).strip()
    character = str(persona.get("character") or row.get("role") or "").strip()

    lines: list[str] = []
    if character and character.lower() not in display.lower():
        lines.append(f"You are {display} — {character}.")
    else:
        lines.append(f"You are {display}.")

    for para in persona.get("opening") or []:
        text = str(para).strip()
        if text:
            lines.append("")
            lines.append(text)

    register = str(persona.get("register") or "").strip()
    if register:
        lines.append("")
        lines.append(f"**Register:** {register}")

    mandate = str(row.get("job") or seed_block.get("instruction") or "").strip()
    if mandate:
        lines.append("")
        lines.append(f"**Mandate:** {mandate}")

    namespace = str(row.get("namespace") or identity.get("namespace") or "").strip()
    if namespace:
        lines.append("")
        ns = namespace if namespace.endswith("/") else f"{namespace}/"
        lines.append(f"**Namespace:** `{ns}` in SOIL and KB.")

    not_job = str(row.get("not_job") or "").strip()
    if not_job:
        lines.append("")
        lines.append(f"**What you do not do:** {not_job}")

    voice_rules = [str(r).strip() for r in (persona.get("voice_rules") or []) if str(r).strip()]
    if voice_rules:
        lines.append("")
        lines.append("**Voice rules:**")
        for rule in voice_rules:
            lines.append(f"- {rule}")

    breaks_voice = [str(r).strip() for r in (persona.get("breaks_voice") or []) if str(r).strip()]
    if breaks_voice:
        lines.append("")
        lines.append("**Breaks voice:**")
        for rule in breaks_voice:
            lines.append(f"- {rule}")

    calibration = str(persona.get("calibration") or "").strip()
    if calibration:
        lines.append("")
        lines.append(f"**Calibration:** {calibration}")

    checksum = str(persona.get("checksum") or seed_block.get("checksum") or DEFAULT_CHECKSUM).strip()
    lines.append("")
    lines.append(f"*{checksum}*")
    lines.append("")
    return "\n".join(lines)


def compile_persona(
    agent_id: str,
    *,
    dry_run: bool = False,
    force: bool = False,
    out_path: Path | None = None,
) -> dict[str, Any]:
    """Write personas/{agent_id}.md from home seed (+ registry row when known)."""
    key = (agent_id or "").strip()
    path = seed_path(key)
    if path is None:
        return {"ok": False, "error": "invalid_agent_id", "agent_id": key}

    data, err = load_seed_document(key)
    if err or data is None:
        return {"ok": False, "error": err or "unreadable", "agent_id": key}

    dest = out_path or (personas_dir() / f"{key}.md")
    rel_dest = str(dest.relative_to(willow_home())) if dest.is_relative_to(willow_home()) else str(dest)

    if dest.is_file() and not force and not dry_run:
        return {
            "ok": True,
            "action": "skipped",
            "agent_id": key,
            "path": rel_dest,
            "reason": "exists (pass --force to overwrite)",
        }

    row = specialist_row(key)
    markdown = render_persona_markdown(key, data, registry_row=row)

    rat = (data.get("seed") or {}).get("ratification") or {}
    status = str(rat.get("status") or "pending").lower()
    advisory = None
    if status != "ratified":
        advisory = "Seed unratified — compiled persona is advisory until sign-seed."

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "agent_id": key,
            "path": rel_dest,
            "ratification_status": status,
            "advisory": advisory,
            "preview": markdown,
        }

    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(markdown, encoding="utf-8")
    return {
        "ok": True,
        "action": "written",
        "agent_id": key,
        "path": rel_dest,
        "ratification_status": status,
        "advisory": advisory,
        "bytes": len(markdown.encode("utf-8")),
    }


def compile_persona_cli_main() -> None:
    parser = argparse.ArgumentParser(
        prog="willow-mcp-compile-persona",
        description="Compile $WILLOW_HOME/seeds/{agent_id}.json → personas/{agent_id}.md",
    )
    parser.add_argument("agent_id", help="agent id (e.g. hanuman, willow)")
    parser.add_argument("--force", action="store_true", help="overwrite existing persona .md")
    parser.add_argument("--dry-run", action="store_true", help="preview markdown without writing")
    parser.add_argument("--out", default="", help="optional output path (default: $WILLOW_HOME/personas/)")
    args = parser.parse_args()
    out = Path(args.out).expanduser() if args.out else None
    print(json.dumps(compile_persona(args.agent_id, dry_run=args.dry_run, force=args.force, out_path=out), indent=2))


def main() -> None:
    compile_persona_cli_main()
