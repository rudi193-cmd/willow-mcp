"""Narrow adapter over the existing Postgres ``frank_ledger`` hash chain."""
from __future__ import annotations

import hashlib
import json
import uuid

from psycopg2.extras import Json, RealDictCursor

TABLE = "frank_ledger"
LOCK_KEY = 8817001


def _payload(event_type: str, content) -> str:
    if isinstance(content, str):
        try:
            content = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            pass
    return json.dumps(
        {"event_type": event_type, "content": content}, sort_keys=True
    )


def entry_hash(prev_hash: str | None, event_type: str, content) -> str:
    return hashlib.sha256(
        f"{prev_hash or ''}{_payload(event_type, content)}".encode()
    ).hexdigest()


class GovernanceLedger:
    def __init__(self, pg):
        self.pg = pg

    def append(self, project: str, event_type: str, content: dict) -> str:
        """Serialize against the shared chain head and append one existing-shape row."""
        record_id = str(uuid.uuid4())
        cur = self.pg.cursor()
        locked = False
        try:
            cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
            locked = True
            cur.execute(
                f"SELECT hash FROM {TABLE} ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            previous = row[0] if row else None
            digest = entry_hash(previous, event_type, content)
            cur.execute(
                f"INSERT INTO {TABLE} "
                "(id, project, event_type, content, prev_hash, hash, created_at) "
                "VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())",
                (
                    record_id,
                    project,
                    event_type,
                    Json(content),
                    previous,
                    digest,
                ),
            )
            self.pg.commit()
            return record_id
        finally:
            if locked:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            cur.close()

    def append_citation(
        self, project: str, content: dict, *, max_count: int | None
    ) -> tuple[str, str]:
        """Atomically meter and append a citation under the shared chain lock."""
        record_id = str(uuid.uuid4())
        cur = self.pg.cursor()
        locked = False
        outcome = str(content.get("outcome", "EAMBIG"))
        try:
            cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
            locked = True
            if outcome == "granted" and max_count is not None:
                cur.execute(
                    f"SELECT COUNT(*) FROM {TABLE} "
                    "WHERE event_type='envelope_citation' "
                    "AND content->>'envelope_id'=%s "
                    "AND content->>'outcome'='granted'",
                    (content["envelope_id"],),
                )
                if int(cur.fetchone()[0]) >= max_count:
                    outcome = "EDQUOT"
                    content = {**content, "outcome": outcome}
            cur.execute(
                f"SELECT hash FROM {TABLE} ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            previous = row[0] if row else None
            digest = entry_hash(previous, "envelope_citation", content)
            cur.execute(
                f"INSERT INTO {TABLE} "
                "(id, project, event_type, content, prev_hash, hash, created_at) "
                "VALUES (%s, %s, 'envelope_citation', %s, %s, %s, clock_timestamp())",
                (record_id, project, Json(content), previous, digest),
            )
            self.pg.commit()
            return record_id, outcome
        finally:
            if locked:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            cur.close()

    def verify(self) -> dict:
        cur = self.pg.cursor()
        cur.execute(
            f"SELECT id, event_type, content, prev_hash, hash "
            f"FROM {TABLE} ORDER BY created_at ASC"
        )
        rows = cur.fetchall()
        cur.close()
        previous = None
        for record_id, event_type, content, prev_hash, stored_hash in rows:
            if (
                prev_hash != previous
                or entry_hash(previous, event_type, content) != stored_hash
            ):
                return {
                    "valid": False,
                    "broken_at": record_id,
                    "count": len(rows),
                }
            previous = stored_hash
        return {"valid": True, "broken_at": None, "count": len(rows)}

    def citation_count(self, envelope_id: str) -> int:
        cur = self.pg.cursor()
        cur.execute(
            f"SELECT COUNT(*) FROM {TABLE} "
            "WHERE event_type = 'envelope_citation' "
            "AND content->>'envelope_id' = %s "
            "AND content->>'outcome' = 'granted'",
            (envelope_id,),
        )
        count = int(cur.fetchone()[0])
        cur.close()
        return count

    def citations(self, envelope_id: str) -> list[dict]:
        cur = self.pg.cursor(cursor_factory=RealDictCursor)
        cur.execute(
            f"SELECT * FROM {TABLE} "
            "WHERE event_type = 'envelope_citation' "
            "AND content->>'envelope_id' = %s ORDER BY created_at ASC",
            (envelope_id,),
        )
        rows = [dict(row) for row in cur.fetchall()]
        cur.close()
        return rows
