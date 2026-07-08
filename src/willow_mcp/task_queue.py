"""Task-queue backends bridging willow-mcp to the `kartikeya` worker.

`kartikeya` (the extracted Kart engine) owns the sandbox + worker loop and is
written against a small `TaskQueue` seam. This module supplies that seam over
willow-mcp's *adopted* `tasks` table (Postgres, via the schema-adaptation layer)
and, when no Postgres is configured, falls back to kartikeya's bundled
`SqliteTaskQueue` — so `willow-mcp worker` runs tasks with or without a DB.

`kartikeya` is an OPTIONAL dependency (`pip install willow-mcp[worker]`); it is
imported lazily so importing willow-mcp never requires it. `WillowMcpTaskQueue`
duck-types the seam (it does not subclass `kartikeya.TaskQueue`) precisely so
this module imports cleanly when kartikeya is absent.
"""
from __future__ import annotations

import json
import os
from pathlib import Path

from psycopg2.extras import Json

from . import schema_profile as sp
from .db import get_pg

_TASK_FIELDS = ["task_id", "task", "submitted_by", "agent", "status", "result",
                "steps", "created_at", "completed_at"]


def _require_kartikeya():
    try:
        import kartikeya  # noqa: F401
        return kartikeya
    except ModuleNotFoundError as e:  # pragma: no cover - exercised where absent
        raise RuntimeError(
            "the task worker requires the 'kartikeya' package — "
            "install it with `pip install willow-mcp[worker]`"
        ) from e


class WillowMcpTaskQueue:
    """kartikeya.TaskQueue seam over willow-mcp's adopted Postgres `tasks` table.

    Resolves the confirmed column mapping once, then speaks the seam's methods in
    the host's real column names. Claim is atomic across concurrent workers via
    `FOR UPDATE SKIP LOCKED`.
    """

    def __init__(self, pg, app_id: str):
        self._pg = pg
        mapping = sp.resolve(pg, app_id, "tasks", _TASK_FIELDS)
        if "error" in mapping:
            raise RuntimeError(mapping["error"])
        if not mapping.get("confirmed"):
            raise RuntimeError(
                "tasks schema mapping is not confirmed — run schema_confirm_mapping "
                "for the 'tasks' table before starting a worker"
            )
        fields = mapping["fields"]
        self._col = {k: fields[k]["column"] for k in _TASK_FIELDS}
        self._result_jsonb = fields["result"].get("data_type") in ("jsonb", "json")
        for req in ("task_id", "task", "agent", "status"):
            if not self._col[req]:
                raise RuntimeError(f"tasks table has no mappable '{req}' column")

    def _q(self, field: str) -> str:
        return f'"{self._col[field]}"'

    def claim_pending(self, agent: str, limit: int, lane: str | None = None):
        from kartikeya import TaskRow  # lazy — this backend is only used with kartikeya present
        c = self._col
        order = c["created_at"] or c["task_id"]
        ret = [c["task_id"], c["task"], c["agent"]]
        if c["submitted_by"]:
            ret.append(c["submitted_by"])
        ret_cols = ", ".join(f'"{x}"' for x in ret)
        sql = (
            f'UPDATE tasks SET {self._q("status")} = \'running\' '
            f'WHERE {self._q("task_id")} IN ('
            f'  SELECT {self._q("task_id")} FROM tasks '
            f'  WHERE {self._q("status")} = \'pending\' AND {self._q("agent")} = %s '
            f'  ORDER BY "{order}" LIMIT %s FOR UPDATE SKIP LOCKED'
            f') RETURNING {ret_cols}'
        )
        cur = self._pg.cursor()
        cur.execute(sql, (agent, limit))
        rows = cur.fetchall()
        cur.close()
        self._pg.commit()
        out = []
        for r in rows:
            submitted_by = r[3] if c["submitted_by"] and len(r) > 3 else ""
            out.append(TaskRow(task_id=r[0], task=r[1] or "", agent=r[2] or agent,
                               submitted_by=submitted_by or "", status="running"))
        return out

    def mark_running(self, task_id: str) -> None:
        cur = self._pg.cursor()
        cur.execute(
            f'UPDATE tasks SET {self._q("status")} = \'running\' '
            f'WHERE {self._q("task_id")} = %s AND {self._q("status")} <> \'running\'',
            (task_id,),
        )
        cur.close()
        self._pg.commit()

    def mark_done(self, task_id: str, *, status: str, result: str) -> None:
        c = self._col
        if self._result_jsonb:
            try:
                stored = Json(json.loads(result))
            except (TypeError, json.JSONDecodeError):
                stored = Json(result)
        else:
            stored = result
        sets = [f'{self._q("status")} = %s', f'{self._q("result")} = %s']
        params = [status, stored]
        if c["completed_at"]:
            sets.append(f'{self._q("completed_at")} = now()')
        cur = self._pg.cursor()
        cur.execute(
            f'UPDATE tasks SET {", ".join(sets)} WHERE {self._q("task_id")} = %s',
            (*params, task_id),
        )
        cur.close()
        self._pg.commit()

    def stats(self):
        from kartikeya import QueueStats
        cur = self._pg.cursor()
        cur.execute(f'SELECT {self._q("status")}, COUNT(*) FROM tasks GROUP BY {self._q("status")}')
        rows = cur.fetchall()
        cur.close()
        by = {r[0]: r[1] for r in rows}
        return QueueStats(
            pending=by.get("pending", 0),
            running=by.get("running", 0),
            completed=by.get("completed", 0),
            failed=by.get("failed", 0),
        )


def build_task_queue(app_id: str):
    """Pick a backend: Postgres (adopted `tasks` table) if reachable, else
    kartikeya's bundled SqliteTaskQueue under WILLOW_STORE_ROOT."""
    pg = get_pg()
    if pg is not None:
        return WillowMcpTaskQueue(pg, app_id)
    k = _require_kartikeya()
    root = os.environ.get("WILLOW_STORE_ROOT") or str(Path.home() / ".willow")
    db_path = Path(root).expanduser() / "kart.db"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    return k.SqliteTaskQueue(str(db_path))
