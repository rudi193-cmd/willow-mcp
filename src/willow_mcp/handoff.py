"""Handoff write/read/verify for dispatch closeout."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .dispatch import dispatch_read, dispatch_set_status
from .paths import dispatch_dir


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def handoff_write_v4(
    app_id: str,
    dispatch_id: str,
    *,
    findings: Optional[list[dict]] = None,
    narrative: str = "",
    checklist_resolved: bool = True,
    envelope_clean: bool = True,
) -> dict:
    pkt = dispatch_read(dispatch_id)
    if pkt.get("error"):
        return pkt
    if pkt["meta"].get("to_app", "").lower() != app_id.lower():
        return {"error": "wrong_recipient", "expected": pkt["meta"].get("to_app")}

    root = dispatch_dir(dispatch_id)
    handoff = {
        "format": "handoff_v1",
        "dispatch_id": dispatch_id,
        "app_id": app_id,
        "reply_to": pkt["meta"].get("reply_to", "willow"),
        "role": pkt["meta"].get("role"),
        "findings": list(findings or []),
        "narrative": narrative,
        "checklist_resolved": checklist_resolved,
        "envelope_clean": envelope_clean,
        "written_at": _utc_now(),
    }
    _write_json(root / "handoff.json", handoff)

    closeout = _render_closeout(dispatch_id, app_id, handoff, pkt)
    (root / "closeout.md").write_text(closeout, encoding="utf-8")

    dispatch_set_status(
        dispatch_id,
        "complete",
        handoff_path=f"dispatch/{dispatch_id}/handoff.json",
    )
    return {
        "dispatch_id": dispatch_id,
        "status": "complete",
        "reply_to": handoff["reply_to"],
        "waiting_for": "verify_handoff",
    }


def _render_closeout(dispatch_id: str, app_id: str, handoff: dict, pkt: dict) -> str:
    lines = [
        f"# Closeout {dispatch_id}",
        "",
        f"**From:** {app_id}",
        f"**To:** {handoff.get('reply_to', 'willow')}",
        f"**Date:** {handoff.get('written_at', '')}",
        "",
        "## What Was Done",
        "",
        handoff.get("narrative") or "(no narrative)",
        "",
        "## Findings",
        "",
    ]
    findings = handoff.get("findings") or []
    if not findings:
        lines.append("- (none)")
    else:
        lines.append("| ID | Finding | Severity | Evidence |")
        lines.append("|----|---------|----------|----------|")
        for f in findings:
            evid = ", ".join(f.get("evidence") or [])
            lines.append(
                f"| {f.get('id', '')} | {f.get('text', '')} | {f.get('severity', '')} | {evid} |"
            )
    lines.extend([
        "",
        "## Checklist",
        "",
        f"- [{'x' if handoff.get('checklist_resolved') else ' '}] All assignment checklist items addressed",
        "",
    ])
    summary = pkt.get("meta", {}).get("summary", "")
    if summary:
        lines.extend(["## Assignment summary", "", summary, ""])
    return "\n".join(lines)


def handoff_read(dispatch_id: str) -> dict:
    root = dispatch_dir(dispatch_id)
    path = root / "handoff.json"
    if not path.exists():
        return {"error": "not_found", "dispatch_id": dispatch_id}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        return {"error": f"read_failed: {e}"}
    closeout_path = root / "closeout.md"
    closeout = closeout_path.read_text(encoding="utf-8") if closeout_path.exists() else ""
    return {"dispatch_id": dispatch_id, "handoff": data, "closeout_md": closeout}


def verify_handoff(dispatch_id: str) -> dict:
    pkt = dispatch_read(dispatch_id)
    if pkt.get("error"):
        return pkt
    st = pkt.get("status", {}).get("status")
    if st != "complete":
        return {"error": "not_complete", "status": st}

    hr = handoff_read(dispatch_id)
    if hr.get("error"):
        return hr
    handoff = hr["handoff"]
    verified = bool(handoff.get("checklist_resolved")) and bool(handoff.get("envelope_clean"))
    findings = handoff.get("findings") or []
    for f in findings:
        if not f.get("text"):
            verified = False
            break

    if verified:
        dispatch_set_status(dispatch_id, "verified", verified_at=_utc_now())

    return {
        "dispatch_id": dispatch_id,
        "verified": verified,
        "checklist_resolved": handoff.get("checklist_resolved"),
        "envelope_clean": handoff.get("envelope_clean"),
        "findings_count": len(findings),
        "status": "verified" if verified else "complete",
    }
