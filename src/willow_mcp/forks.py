"""forks — bounded work-unit tracking for branch + PR workflows.

Ported from willow-2.0 `willow/forks.py` (migration shortlist §6). Deliberate
departure: **SOIL-backed, not fleet Postgres.** willow-2.0 stored forks in a
`forks` table and tagged `knowledge.fork_id` on merge; that drags a schema
migration into the shared fleet database (B-28). Forks are durable keyed records
with an append-only change log — the same shape as gaps, lineage, and the human
loop queue — so they live in the SOIL store.

`fork_merge` / `fork_delete` count atom/kb change-log refs as promoted/archived
bookkeeping. Full Postgres `knowledge.fork_id` promotion remains a fleet concern
when the host KB exposes that column.
"""
from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

FORKS_COLLECTION = "forks"
OPEN = "open"
MERGED = "merged"
DELETED = "deleted"
STATUSES = (OPEN, MERGED, DELETED)
CHANGE_TYPES = ("branch", "atom", "task", "thread", "note", "git", "kb", "review")

ENV_SNAPSHOT_PREFIXES = (
    "WILLOW_", "GROVE_", "HOME", "USER", "PATH",
    "PGUSER", "PGHOST", "PGPORT",
)


class ForkError(Exception):
    """Bad input to a fork primitive."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _fork_id(custom: str = "") -> str:
    fid = (custom or "").strip()
    if fid:
        return fid
    return f"FORK-{uuid.uuid4().hex[:8].upper()}"


def _clean(record: dict) -> dict:
    return {k: v for k, v in record.items() if not k.startswith("_")}


def _env_snapshot() -> dict[str, str]:
    return {
        k: v for k, v in os.environ.items()
        if any(k == p or k.startswith(p) for p in ENV_SNAPSHOT_PREFIXES)
    }


def _get(store, fork_id: str) -> Optional[dict]:
    rec = store.get(FORKS_COLLECTION, record_id=fork_id)
    return _clean(rec) if isinstance(rec, dict) and rec.get("fork_id") else None


def _put(store, record: dict) -> dict:
    store.put(FORKS_COLLECTION, record, record_id=record["fork_id"])
    return record


def _atom_refs(changes: list) -> list[str]:
    refs: list[str] = []
    for ch in changes:
        if not isinstance(ch, dict):
            continue
        if ch.get("type") in ("atom", "kb"):
            ref = (ch.get("ref") or "").strip()
            if ref:
                refs.append(ref)
    return refs


def create(
    store,
    *,
    app_id: str,
    title: str,
    created_by: str,
    topic: str = "",
    fork_id: str = "",
) -> dict:
    title = (title or "").strip()
    created_by = (created_by or "").strip()
    if not title:
        raise ForkError("title is required")
    if not created_by:
        raise ForkError("created_by is required")
    fid = _fork_id(fork_id)
    if _get(store, fid):
        raise ForkError(f"fork {fid} already exists")
    record = {
        "fork_id": fid,
        "app_id": app_id,
        "title": title,
        "created_by": created_by,
        "topic": (topic or "").strip(),
        "status": OPEN,
        "participants": [created_by],
        "changes": [],
        "created_at": _now(),
        "merged_at": None,
        "deleted_at": None,
        "outcome_note": "",
        "env_snapshot": _env_snapshot(),
    }
    return _put(store, record)


def join(store, *, fork_id: str, component: str) -> dict:
    component = (component or "").strip()
    if not component:
        raise ForkError("component is required")
    rec = _get(store, fork_id)
    if not rec:
        return {"error": f"fork {fork_id} not found"}
    participants = list(rec.get("participants") or [])
    if component not in participants:
        participants.append(component)
    rec["participants"] = participants
    _put(store, rec)
    return {"fork_id": fork_id, "participants": participants}


def log_change(
    store,
    *,
    fork_id: str,
    component: str,
    type_: str,
    ref: str,
    description: str = "",
) -> dict:
    component = (component or "").strip()
    type_ = (type_ or "").strip().lower()
    ref = (ref or "").strip()
    if not component or not type_ or not ref:
        raise ForkError("component, type, and ref are required")
    if type_ not in CHANGE_TYPES:
        raise ForkError(f"invalid type {type_!r}; expected one of {CHANGE_TYPES}")
    rec = _get(store, fork_id)
    if not rec:
        return {"error": f"fork {fork_id} not found"}
    if rec.get("status") != OPEN:
        return {"error": f"fork {fork_id} is not open (status={rec.get('status')})"}
    changes = list(rec.get("changes") or [])
    changes.append({
        "component": component,
        "type": type_,
        "ref": ref,
        "description": description or "",
        "logged_at": _now(),
    })
    rec["changes"] = changes
    _put(store, rec)
    return {"logged": True, "change_count": len(changes)}


def merge(store, *, fork_id: str, outcome_note: str = "") -> dict:
    rec = _get(store, fork_id)
    if not rec:
        return {"merged": False, "reason": "fork not found"}
    if rec.get("status") != OPEN:
        return {"merged": False, "reason": "fork not open"}
    rec["status"] = MERGED
    rec["merged_at"] = _now()
    rec["outcome_note"] = outcome_note or ""
    _put(store, rec)
    promoted = len(_atom_refs(rec.get("changes") or []))
    return {"merged": True, "promoted_count": promoted}


def delete(store, *, fork_id: str, reason: str = "") -> dict:
    rec = _get(store, fork_id)
    if not rec:
        return {"deleted": False, "reason": "fork not found"}
    if rec.get("status") != OPEN:
        return {"deleted": False, "reason": "fork not open"}
    rec["status"] = DELETED
    rec["deleted_at"] = _now()
    rec["outcome_note"] = reason or ""
    _put(store, rec)
    archived = len(_atom_refs(rec.get("changes") or []))
    return {"deleted": True, "archived_count": archived}


def status(store, *, fork_id: str) -> Optional[dict]:
    return _get(store, fork_id)


def list_forks(store, *, status: str = OPEN, limit: int = 100) -> list[dict]:
    status = (status or OPEN).strip().lower()
    if status not in STATUSES:
        raise ForkError(f"invalid status {status!r}; expected one of {STATUSES}")
    rows = [_clean(r) for r in store.all(FORKS_COLLECTION)
            if isinstance(r, dict) and r.get("fork_id")]
    rows = [r for r in rows if r.get("status") == status]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    out: list[dict] = []
    for r in rows[:max(0, limit)]:
        changes = r.get("changes") or []
        participants = r.get("participants") or []
        out.append({
            "fork_id": r["fork_id"],
            "title": r.get("title", ""),
            "created_at": r.get("created_at", ""),
            "created_by": r.get("created_by", ""),
            "topic": r.get("topic", ""),
            "participant_count": len(participants),
            "change_count": len(changes),
        })
    return out


def env_check(store, *, fork_id: str) -> dict:
    rec = _get(store, fork_id)
    if not rec:
        return {"error": f"fork {fork_id} not found"}
    snapshot = rec.get("env_snapshot") or {}
    if not snapshot:
        return {"error": f"No env snapshot for fork {fork_id}. Was fork_create called?"}
    current = _env_snapshot()
    added = {k: current[k] for k in current if k not in snapshot}
    removed = {k: snapshot[k] for k in snapshot if k not in current}
    changed = {
        k: {"was": snapshot[k], "now": current[k]}
        for k in current
        if k in snapshot and current[k] != snapshot[k]
    }
    return {
        "fork_id": fork_id,
        "added": added,
        "removed": removed,
        "changed": changed,
        "clean": not (added or removed or changed),
    }
