"""Dispatch packet I/O — meta.json, assignment.md, status.json under $WILLOW_HOME/dispatch/."""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from .paths import (
    dispatch_dir,
    dispatch_root,
    handoffs_dir,
    new_dispatch_id,
    session_path,
    sessions_dir,
)
from .human_session import is_orchestrator_app
from .registry import persona_context
from .seed_loader import seed_context
from .roles import VALID_STATUSES

_AGENT_DOC = "docs/AGENTS.md"
_PROJECT_RE = re.compile(r"^[A-Za-z0-9_.-]{1,128}$")

logger = logging.getLogger("willow_mcp.dispatch")


# ── best-effort Postgres mirror (fleet visibility) ─────────────────────────────
# Dispatch packets are filesystem-canonical (a standalone install has no
# Postgres). But the fleet reads the *other* willow-mcp state — store, knowledge,
# tasks, agents — from a shared Postgres; dispatch is the one subsystem it can't
# see. When an operator runs willow-mcp as a fleet host (WILLOW_MCP_DISPATCH_MIRROR
# truthy) *and* a host DB is reachable, mirror each packet's routing/status into a
# `dispatch_tasks` table so the fleet sees dispatches too. This is NEVER load-
# bearing: the filesystem packet is the source of truth, the mirror is opt-in and
# off by default, and every failure here is swallowed — a broken or absent DB must
# not affect a dispatch that already wrote to disk. See docs/schema/
# dispatch_tasks.postgres.sql.

_DISPATCH_TASKS_DDL = """
CREATE TABLE IF NOT EXISTS dispatch_tasks (
    dispatch_id text PRIMARY KEY,
    from_app    text        NOT NULL DEFAULT '',
    to_app      text        NOT NULL DEFAULT '',
    role        text        NOT NULL DEFAULT '',
    phase       text        NOT NULL DEFAULT '',
    priority    text        NOT NULL DEFAULT 'normal',
    reply_to    text        NOT NULL DEFAULT '',
    summary     text        NOT NULL DEFAULT '',
    status      text        NOT NULL DEFAULT 'pending',
    created_at  timestamptz NOT NULL DEFAULT now(),
    updated_at  timestamptz NOT NULL DEFAULT now()
);
"""


def dispatch_mirror_enabled() -> bool:
    """True when the operator has opted this install into mirroring dispatch
    packets to a shared Postgres (fleet-host duty). Off by default — a standalone
    install stays filesystem-only and never reaches for a DB."""
    return bool(os.environ.get("WILLOW_MCP_DISPATCH_MIRROR", "").strip())


def _pg_mirror_upsert(meta: dict) -> None:
    """Best-effort: mirror a packet's routing + status into `dispatch_tasks`.
    Silent no-op when mirroring is off or no host DB is reachable; never raises —
    the filesystem packet has already been written and is canonical."""
    if not dispatch_mirror_enabled():
        return
    try:
        from . import db
        conn = db.get_pg()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(_DISPATCH_TASKS_DDL)
        cur.execute(
            "INSERT INTO dispatch_tasks (dispatch_id, from_app, to_app, role, "
            "phase, priority, reply_to, summary, status, created_at, updated_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, now(), now()) "
            "ON CONFLICT (dispatch_id) DO UPDATE SET "
            "status = EXCLUDED.status, summary = EXCLUDED.summary, updated_at = now()",
            (
                meta.get("dispatch_id", ""), meta.get("from_app", ""),
                meta.get("to_app", ""), meta.get("role", ""), meta.get("phase", ""),
                meta.get("priority", "normal"), meta.get("reply_to", ""),
                meta.get("summary", ""), meta.get("status", "pending"),
            ),
        )
        cur.close()
    except Exception:  # best-effort: a DB fault must never break a written packet
        logger.debug("dispatch: PG mirror upsert skipped", exc_info=True)


def _pg_mirror_status(dispatch_id: str, status: str) -> None:
    """Best-effort: reflect a status transition into `dispatch_tasks`. A row that
    doesn't exist (mirror enabled after the packet was created) is a no-op UPDATE,
    which is acceptable — the next transition or a re-send upserts it."""
    if not dispatch_mirror_enabled():
        return
    try:
        from . import db
        conn = db.get_pg()
        if conn is None:
            return
        cur = conn.cursor()
        cur.execute(_DISPATCH_TASKS_DDL)
        cur.execute(
            "UPDATE dispatch_tasks SET status = %s, updated_at = now() "
            "WHERE dispatch_id = %s",
            (status, (dispatch_id or "").upper()),
        )
        cur.close()
    except Exception:
        logger.debug("dispatch: PG mirror status skipped", exc_info=True)


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _read_json(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def project_context(project: str = "", workspace: str = "") -> dict:
    root_value = (
        workspace
        or os.environ.get("WILLOW_PROJECT_ROOT", "")
    ).strip()
    root = Path(root_value).expanduser().resolve() if root_value else None
    name = (project or os.environ.get("WILLOW_HANDOFF_PROJECT", "")).strip()
    derived = False
    if not name and root:
        # Collision-safe derivation (Loki C303AA2F §3.5): the bare basename
        # collides — /a/charter and /b/charter would share one project state.
        # Disambiguate a human-readable prefix with a short digest of the
        # *canonical* (resolved) path so distinct workspaces never merge. An
        # explicit project id always wins over this and is used verbatim.
        digest = hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:8]
        prefix = re.sub(r"[^A-Za-z0-9_.-]", "-", root.name).strip("-") or "project"
        name = f"{prefix}-{digest}"
        derived = True
    if name and not _PROJECT_RE.fullmatch(name):
        return {"error": "invalid_project", "project": name}
    return {
        "name": name or None,
        "root": str(root) if root else None,
        "workspace": str(root) if root else (workspace or None),
        "derived_from_workspace": derived,
    }


def dispatch_send(
    from_app: str,
    to_app: str,
    assignment_md: str,
    *,
    role: str = "",
    reply_to: str = "willow",
    summary: str = "",
    phase: str = "operate",
    priority: str = "normal",
    context_refs: Optional[list[str]] = None,
    dispatch_id: str = "",
) -> dict:
    """Create dispatch/{id}/ with meta, assignment, and status pending."""
    if not (assignment_md or "").strip():
        return {"error": "assignment_required"}
    did = (dispatch_id or new_dispatch_id()).upper()
    root = dispatch_dir(did)
    if root.exists():
        return {"error": "dispatch_exists", "dispatch_id": did}

    role = (role or to_app).lower()
    rel_assignment = f"dispatch/{did}/assignment.md"
    meta = {
        "format": "startup_packet_meta_v1",
        "version": 1,
        "dispatch_id": did,
        "from_app": from_app,
        "to_app": to_app,
        "role": role,
        "phase": phase,
        "reply_to": reply_to,
        "priority": priority,
        "reply_contract": "handoff_v4",
        "assignment_path": rel_assignment,
        "context_refs": list(context_refs or []),
        "summary": (summary or "").strip() or _first_line(assignment_md),
        "created_at": _utc_now(),
        "status": "pending",
    }
    status = {
        "status": "pending",
        "updated_at": meta["created_at"],
        "handoff_path": None,
        "verified_at": None,
        "cleared_at": None,
    }

    root.mkdir(parents=True, exist_ok=False)
    _write_json(root / "meta.json", meta)
    (root / "assignment.md").write_text(assignment_md.strip() + "\n", encoding="utf-8")
    _write_json(root / "status.json", status)
    _pg_mirror_upsert(meta)  # best-effort fleet mirror; filesystem is canonical

    return {
        "dispatch_id": did,
        "to_app": to_app,
        "from_app": from_app,
        "status": "pending",
        "assignment_path": str(root / "assignment.md"),
        "summary": meta["summary"],
    }


def _first_line(md: str) -> str:
    for line in md.splitlines():
        s = line.strip().lstrip("#").strip()
        if s:
            return s[:200]
    return "dispatch assignment"


def dispatch_read(dispatch_id: str) -> dict:
    root = dispatch_dir(dispatch_id)
    meta = _read_json(root / "meta.json")
    if not meta:
        return {"error": "not_found", "dispatch_id": dispatch_id}
    status = _read_json(root / "status.json") or {}
    assignment_path = root / "assignment.md"
    assignment = ""
    if assignment_path.exists():
        assignment = assignment_path.read_text(encoding="utf-8")
    return {
        "dispatch_id": dispatch_id,
        "meta": meta,
        "status": status,
        "assignment": assignment,
    }


def dispatch_list(
    *,
    to_app: str = "",
    from_app: str = "",
    status: str = "",
    limit: int = 20,
) -> dict:
    disp_root = dispatch_root()
    if not disp_root.is_dir():
        return {"dispatches": [], "total": 0}

    rows: list[dict] = []
    for child in sorted(disp_root.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not child.is_dir():
            continue
        meta = _read_json(child / "meta.json")
        st = _read_json(child / "status.json") or {}
        if not meta:
            continue
        if to_app and meta.get("to_app", "").lower() != to_app.lower():
            continue
        if from_app and meta.get("from_app", "").lower() != from_app.lower():
            continue
        cur_status = st.get("status") or meta.get("status") or "pending"
        if status and cur_status != status:
            continue
        rows.append({
            "dispatch_id": meta.get("dispatch_id", child.name),
            "from_app": meta.get("from_app"),
            "to_app": meta.get("to_app"),
            "role": meta.get("role"),
            "summary": meta.get("summary", ""),
            "status": cur_status,
            "created_at": meta.get("created_at"),
            "reply_to": meta.get("reply_to"),
        })
        if len(rows) >= limit:
            break
    return {"dispatches": rows, "total": len(rows)}


def dispatch_set_status(dispatch_id: str, status: str, **extra: Any) -> dict:
    if status not in VALID_STATUSES:
        return {"error": "invalid_status", "status": status}
    root = dispatch_dir(dispatch_id)
    path = root / "status.json"
    data = _read_json(path)
    if data is None:
        return {"error": "not_found", "dispatch_id": dispatch_id}
    data["status"] = status
    data["updated_at"] = _utc_now()
    for key, val in extra.items():
        if val is not None:
            data[key] = val
    _write_json(path, data)
    meta_path = root / "meta.json"
    meta = _read_json(meta_path)
    if meta:
        meta["status"] = status
        _write_json(meta_path, meta)
    _pg_mirror_status(dispatch_id, status)  # best-effort fleet mirror
    return {"dispatch_id": dispatch_id, "status": status}


def dispatch_accept(dispatch_id: str, app_id: str, session_id: str = "") -> dict:
    """Specialist takes packet: pending → working."""
    pkt = dispatch_read(dispatch_id)
    if pkt.get("error"):
        return pkt
    if pkt["meta"].get("to_app", "").lower() != app_id.lower():
        return {"error": "wrong_recipient", "expected": pkt["meta"].get("to_app")}
    cur = pkt.get("status", {}).get("status", "pending")
    if cur not in ("pending", "cleared"):
        return {"error": "invalid_transition", "from": cur, "to": "working"}
    dispatch_set_status(dispatch_id, "working")
    if session_id:
        session_bind(app_id, session_id, dispatch_id, "working")
    return dispatch_read(dispatch_id)


def session_bind(app_id: str, session_id: str, dispatch_id: str, status: str) -> dict:
    sessions_dir().mkdir(parents=True, exist_ok=True)
    data = {
        "app_id": app_id,
        "session_id": session_id,
        "status": status,
        "dispatch_id": dispatch_id,
        "updated_at": _utc_now(),
    }
    _write_json(session_path(app_id, session_id), data)
    return data


def session_read(app_id: str, session_id: str) -> dict:
    data = _read_json(session_path(app_id, session_id))
    if not data:
        return {"error": "not_found"}
    return data


def _pending_for_app(app_id: str) -> dict | None:
    rows = dispatch_list(to_app=app_id, status="pending", limit=1)
    dispatches = rows.get("dispatches") or []
    return dispatches[0] if dispatches else None


def session_enter(
    app_id: str,
    session_id: str,
    dispatch_id: str = "",
    project: str = "",
    workspace: str = "",
) -> dict:
    """Resolve session entry mode: human prompt vs dispatch id path.

    Orchestrator (willow) is human-only — never dispatch entry. See human-orchestrator.md.
    """
    project_info = project_context(project, workspace)
    if project_info.get("error"):
        return project_info

    # ── Orchestrator seat: human operator only; no agent, no packet boot ──
    if is_orchestrator_app(app_id):
        did = (dispatch_id or "").strip().upper()
        if did:
            return {
                "entry_mode": "human_orchestrator",
                "app_id": app_id,
                "session_id": session_id,
                "error": "orchestrator_human_only",
                "message": (
                    "Willow is human-only. dispatch_id is not accepted. "
                    "Agents cannot run the orchestrator seat."
                ),
            }
        session_bind(app_id, session_id, "", "idle")
        return {
            "entry_mode": "human_orchestrator",
            "app_id": app_id,
            "session_id": session_id,
            "dispatch_id": None,
            "agent_doc": _AGENT_DOC,
            "agent_doc_section": "orchestrator",
            "closeout_tools": ["session_handoff_write"],
            "project": project_info,
            "message": (
                "Human orchestrator entry. Desk: dispatch_list. "
                "Assign with dispatch_send (human host only). "
                "Never dispatch entry for willow."
            ),
            **persona_context(app_id),
            **seed_context(app_id),
        }

    did = (dispatch_id or "").strip().upper()

    if not did:
        existing = session_read(app_id, session_id)
        if not existing.get("error") and existing.get("dispatch_id"):
            did = str(existing["dispatch_id"]).upper()

    if not did:
        pending = _pending_for_app(app_id)
        if pending:
            did = pending["dispatch_id"]

    if not did:
        session_bind(app_id, session_id, "", "idle")
        return {
            "entry_mode": "human",
            "app_id": app_id,
            "session_id": session_id,
            "dispatch_id": None,
            "agent_doc": _AGENT_DOC,
            "agent_doc_section": "specialist",
            "closeout_tools": ["context_save", "session_handoff_write"],
            "project": project_info,
            "message": "Human entry — no dispatch_id. Use human-facing agent and output.",
            **persona_context(app_id),
            **seed_context(app_id),
        }

    pkt = dispatch_read(did)
    if pkt.get("error"):
        return {"entry_mode": "dispatch", "error": pkt["error"], "dispatch_id": did}

    if pkt["meta"].get("to_app", "").lower() != app_id.lower():
        return {
            "entry_mode": "dispatch",
            "error": "wrong_recipient",
            "dispatch_id": did,
            "expected": pkt["meta"].get("to_app"),
        }

    cur = pkt.get("status", {}).get("status", "pending")
    if cur == "pending":
        pkt = dispatch_accept(did, app_id, session_id)
    elif session_id:
        session_bind(app_id, session_id, did, cur)

    return {
        "entry_mode": "dispatch",
        "app_id": app_id,
        "session_id": session_id,
        "dispatch_id": did,
        "agent_doc": _AGENT_DOC,
        "agent_doc_section": "specialist",
        "role": pkt.get("meta", {}).get("role"),
        "assignment": pkt.get("assignment", ""),
        "summary": pkt.get("meta", {}).get("summary", ""),
        "closeout_tools": ["handoff_write_v4"],
        "project": project_info,
        "status": pkt.get("status", {}).get("status"),
        **persona_context(app_id),
        **seed_context(app_id),
    }


def session_handoff_write(
    app_id: str,
    session_id: str,
    *,
    narrative: str,
    summary: str = "",
    findings: Optional[list[dict]] = None,
    next_bite: str = "",
    project: str = "",
    workspace: str = "",
) -> dict:
    """Project-scoped v3 human-entry closeout — no dispatch_id required."""
    project_info = project_context(project, workspace)
    if project_info.get("error"):
        return project_info
    sessions_dir().mkdir(parents=True, exist_ok=True)
    handoffs = handoffs_dir(app_id)
    project_name = project_info.get("name")
    if project_name:
        handoffs = handoffs / project_name
    handoffs.mkdir(parents=True, exist_ok=True)
    stamp = _utc_now()[:10]
    hid = new_dispatch_id()[:8].lower()
    path = handoffs / f"session_handoff-{stamp}-{hid}_{app_id}.md"
    lines = [
        f"# Session handoff — {app_id}",
        "",
        "**Format:** session_handoff_v3",
        f"**Entry mode:** human",
        f"**Session:** {session_id}",
        f"**Project:** {project_name or ''}",
        f"**Workspace:** {project_info.get('workspace') or ''}",
        f"**Written:** {_utc_now()}",
        "",
        "## Summary",
        "",
        summary or narrative[:500],
        "",
        "## Narrative",
        "",
        narrative,
        "",
    ]
    if findings:
        lines.extend(["## Findings", ""])
        for f in findings:
            if isinstance(f, str):
                lines.append(f"- {f}")
                continue
            if not isinstance(f, dict):
                continue
            lines.append(f"- **{f.get('id', 'finding')}** ({f.get('severity', '')}): {f.get('text', '')}")
        lines.append("")
    if next_bite:
        lines.extend(["## Next bite", "", next_bite, ""])
    body = "\n".join(lines)
    path.write_text(body, encoding="utf-8")
    session_bind(app_id, session_id, "", "idle")
    return {
        "entry_mode": "human",
        "format": "session_handoff_v3",
        "project": project_info,
        "handoff_path": str(path),
        "continuity_key": f"handoff/{stamp}-{hid}",
    }


def latest_project_handoff(app_id: str, project: str) -> dict | None:
    if not project or not _PROJECT_RE.fullmatch(project):
        return None
    root = handoffs_dir(app_id) / project
    if not root.is_dir():
        return None
    paths = sorted(
        root.glob("session_handoff-*.md"),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    if not paths:
        return None
    path = paths[0]
    return {"path": str(path), "content": path.read_text(encoding="utf-8")}


def agent_clear(target_app: str, dispatch_id: str, session_id: str = "") -> dict:
    """Orchestrator clears specialist after verify: → cleared."""
    pkt = dispatch_read(dispatch_id)
    if pkt.get("error"):
        return pkt
    st = pkt.get("status", {}).get("status")
    if st not in ("complete", "verified"):
        return {"error": "not_ready_for_clear", "status": st}
    dispatch_set_status(
        dispatch_id,
        "cleared",
        cleared_at=_utc_now(),
    )
    if session_id:
        session_bind(target_app, session_id, "", "idle")
    return {"dispatch_id": dispatch_id, "target_app": target_app, "status": "cleared"}
