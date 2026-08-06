"""Authoritative per-session open-state snapshot (Stop hook write, session_enter read)."""

from __future__ import annotations

import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from typing import Any

from .db import Store, get_pg
from .paths import store_root

_RECORD_ID = "current"
_AGENT_RE = re.compile(r"^[a-zA-Z0-9_\-]{1,64}$")


def stack_collection(app_id: str) -> str:
    key = (app_id or "willow").strip().lower()
    if not _AGENT_RE.match(key):
        key = "willow"
    return f"{key}_session_stack"


def _store() -> Store:
    return Store(str(store_root()))


def read_stack_snapshot(app_id: str) -> dict[str, Any]:
    """Return the latest snapshot record or {}."""
    rec = _store().get(stack_collection(app_id), _RECORD_ID)
    if not rec:
        return {}
    return {k: v for k, v in rec.items() if not k.startswith("_")}


def normalize_stack_record(snap: Any) -> dict[str, Any]:
    if not isinstance(snap, dict) or snap.get("error") == "not_found":
        return {}
    return snap


def parse_task_rows(result: Any) -> list[dict[str, Any]]:
    rows: list = []
    if isinstance(result, dict):
        rows = result.get("pending") or []
    elif isinstance(result, list):
        rows = result
    return [
        {
            "id": str(t.get("task_id") or t.get("id") or ""),
            # str() rather than a bare slice: the columns are discovered, so
            # `task` is not guaranteed to be text, and a hook is the wrong place
            # to learn that slicing an int raises.
            "title": str(t.get("task") or t.get("title") or "")[:80],
            "status": t.get("status", "pending"),
        }
        for t in rows
        if isinstance(t, dict)
    ]


def _fetch_pending_tasks(app_id: str, limit: int = 10) -> list[dict[str, Any]]:
    """This app's still-pending tasks, oldest first.

    Two things here are deliberate rather than incidental, and both mirror
    `server.task_list` (the gated tool this is the hook-safe twin of):

      * **The `submitted_by` filter.** The snapshot is written to a per-app
        collection and replayed into *that* app's SessionStart INDEX, so an
        unfiltered `WHERE status = 'pending'` would put every agent's queued
        work in every agent's boot block. `task_submit` stores `app_id` in
        `submitted_by` (server.py), which is the column that makes the
        snapshot's scope match the collection's.
      * **Going through `schema_profile.resolve`.** The `tasks` table's column
        names are discovered per install, not assumed — that whole layer exists
        because they differ. Hardcoding `task_id, task, status, created_at`
        would raise `UndefinedColumn` on any install that named them otherwise,
        and the `except` below would render that as "no open tasks" rather than
        as "could not tell".

    Fails quiet by design: a hook must not take the session down. An install
    whose mapping has no `submitted_by` column returns nothing rather than
    falling back to the unfiltered query — showing another agent's stack is
    worse than showing none.
    """
    pg = get_pg()
    if not pg:
        return []
    try:
        from . import schema_profile as sp

        mapping = sp.resolve(pg, app_id, "tasks", ["task_id", "task", "status",
                                                   "submitted_by", "created_at"])
        if "error" in mapping:
            return []
        fields = mapping["fields"]
        cols = {name: (fields.get(name) or {}).get("column") for name in
                ("task_id", "task", "status", "submitted_by", "created_at")}
        if not (cols["task_id"] and cols["status"] and cols["submitted_by"]):
            return []

        order_col = cols["created_at"] or cols["task_id"]
        cur = pg.cursor()
        cur.execute(
            f'SELECT "{cols["task_id"]}", "{cols["task"] or cols["task_id"]}", '
            f'"{cols["status"]}" FROM tasks '
            f'WHERE "{cols["status"]}" = \'pending\' AND "{cols["submitted_by"]}" = %s '
            f'ORDER BY "{order_col}" NULLS LAST LIMIT %s',
            (app_id, limit),
        )
        rows = cur.fetchall()
        cur.close()
        return parse_task_rows(
            {"pending": [{"task_id": r[0], "task": r[1], "status": r[2]} for r in rows]}
        )
    except Exception:
        return []


def _fetch_handoff_meta(app_id: str, project: str) -> tuple[str, list[Any]]:
    if not project:
        return "", []
    try:
        from . import dispatch

        h = dispatch.latest_project_handoff(app_id, project)
        if not h or h.get("error"):
            return "", []
        title = h.get("filename") or h.get("path") or ""
        threads: list[Any] = []
        content = h.get("content") or ""
        for line in content.splitlines():
            if line.strip().startswith("- ") and "thread" in line.lower():
                threads.append(line.strip()[2:][:120])
        return str(title)[:120], threads[:5]
    except Exception:
        return "", []


def _fetch_open_gaps(limit: int = 5) -> list[str]:
    try:
        from . import gaps

        rows = gaps.list_gaps(status="open", limit=limit)
        out = []
        for row in rows or []:
            if isinstance(row, dict):
                topic = row.get("topic", "")
                q = row.get("question", "")
                out.append(f"{topic}: {q}"[:120])
        return out
    except Exception:
        return []


def write_stack_snapshot(
    app_id: str,
    session_id: str,
    *,
    project: str = "",
) -> dict[str, Any]:
    """Collect open state and persist to SOIL. Never raises."""
    project = project or os.environ.get("WILLOW_HANDOFF_PROJECT", "")
    with ThreadPoolExecutor(max_workers=3) as ex:
        ft = ex.submit(_fetch_pending_tasks, app_id)
        fh = ex.submit(_fetch_handoff_meta, app_id, project)
        fg = ex.submit(_fetch_open_gaps)
        tasks = ft.result()
        handoff_title, open_threads = fh.result()
        open_decisions = fg.result()

    record = {
        "id": _RECORD_ID,
        "session_id": session_id,
        "written_at": datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        "open_tasks": tasks,
        "open_threads": open_threads,
        "open_decisions": open_decisions,
        "handoff_title": handoff_title,
        "agent": app_id,
        "project": project,
    }
    try:
        _store().put(stack_collection(app_id), record, record_id=_RECORD_ID)
        return {"ok": True, "collection": stack_collection(app_id), "record_id": _RECORD_ID}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}
