"""Narrow adapter over the existing Postgres ``frank_ledger`` hash chain.

Threat model (#280), written down rather than implied:

* The chain is tamper-EVIDENT against anyone who can write rows but cannot
  rewrite the whole table consistently. It is NOT tamper-proof against the
  database operator: ``rechain()`` re-hashes rows from their current content,
  so *edit a row, run rechain()* yields a chain ``verify()`` calls valid —
  the migration and the forgery are the same operation.
* A hash chain vouches for every line except the newest. The close is a head
  recorded somewhere the chain's writer cannot reach: ``verify()`` takes
  ``expected_head`` for exactly that — hold the ``head`` value it returns in
  a CI variable, a monitoring system, an ops runbook, anywhere outside this
  database — and a silent relink becomes a detected one.
* ``rechain()`` is additionally self-documenting: a run that migrated
  anything appends a ``governance.rechain`` row recording the pre-migration
  head and row count. That raises the cost of a QUIET relink; it does not
  stop a determined operator (who can delete the marker and relink again) —
  only an externally-held head does. FRANK mirroring into this table gives
  Nestor "someone else remembers" ONLY to the extent that this someone's
  head is anchored outside; without an anchor it degrades to "someone else
  has a copy that will agree with whatever it now says."
"""
from __future__ import annotations

import hashlib
import json
import uuid

# psycopg2 is imported lazily inside the DB methods so the pure hash functions
# (entry_hash / entry_hash_v2) import and test without a database present.

TABLE = "frank_ledger"
LOCK_KEY = 8817001


def _decode(content):
    if isinstance(content, str):
        try:
            return json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return content
    return content


def _payload(event_type: str, content) -> str:
    return json.dumps(
        {"event_type": event_type, "content": _decode(content)}, sort_keys=True
    )


def entry_hash(prev_hash: str | None, event_type: str, content) -> str:
    """v1 — legacy coverage: hashes only event_type + content. Retained so
    pre-A7 rows still verify; NOT used for new appends (see entry_hash_v2)."""
    return hashlib.sha256(
        f"{prev_hash or ''}{_payload(event_type, content)}".encode()
    ).hexdigest()


def _payload_v2(record_id: str, project: str, event_type: str, content) -> str:
    return json.dumps(
        {"id": record_id, "project": project, "event_type": event_type,
         "content": _decode(content)}, sort_keys=True)


def entry_hash_v2(prev_hash: str | None, record_id: str, project: str,
                  event_type: str, content) -> str:
    """v2 (box audit A7): the hash now covers ``id`` and ``project`` as well.
    v1 excluded them, so FRANK's ``project`` column could be re-pointed by a
    direct UPDATE and ``verify()`` — which re-hashed only event_type+content —
    would not notice. (``created_at`` is server-set by clock_timestamp() and so
    is not known at hash time; it stays out of the digest.)"""
    return hashlib.sha256(
        f"{prev_hash or ''}{_payload_v2(record_id, project, event_type, content)}".encode()
    ).hexdigest()


class GovernanceLedger:
    def __init__(self, pg):
        self.pg = pg

    def _chain_insert(
        self, cur, record_id: str, project: str, event_type: str, content: dict
    ) -> str:
        """Read the current head and append one row chained to it.

        The session advisory lock already serializes cooperating writers, so the
        prev_hash race only arises against a writer that did not take the lock.
        The ``frank_ledger_no_fork`` UNIQUE index (docs/schema/frank-ledger-
        prevent-fork.sql) turns that into an IntegrityError instead of a silent
        fork; here we re-read the new head and retry, bounded, so the chain stays
        single-headed no matter which writer wins (§4.1).
        """
        import psycopg2
        from psycopg2.extras import Json
        for _ in range(5):
            cur.execute(
                f"SELECT hash FROM {TABLE} ORDER BY created_at DESC LIMIT 1"
            )
            row = cur.fetchone()
            previous = row[0] if row else None
            digest = entry_hash_v2(previous, record_id, project, event_type, content)
            try:
                cur.execute(
                    f"INSERT INTO {TABLE} "
                    "(id, project, event_type, content, prev_hash, hash, created_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s, clock_timestamp())",
                    (record_id, project, event_type, Json(content), previous, digest),
                )
                self.pg.commit()
                return digest
            except psycopg2.IntegrityError:
                self.pg.rollback()
        raise RuntimeError("frank chain append could not converge without forking")

    def append(self, project: str, event_type: str, content: dict) -> str:
        """Serialize against the shared chain head and append one existing-shape row."""
        record_id = str(uuid.uuid4())
        cur = self.pg.cursor()
        locked = False
        try:
            cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
            locked = True
            self._chain_insert(cur, record_id, project, event_type, content)
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
            self._chain_insert(cur, record_id, project, "envelope_citation", content)
            return record_id, outcome
        finally:
            if locked:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            cur.close()

    def verify(self, expected_head: str | None = None) -> dict:
        """Walk the chain. ``expected_head`` is the externally-held anchor:
        pass the ``head`` a previous verify returned (kept OUTSIDE this
        database) and "is this the same chain it was yesterday?" gets an
        answer, which internal consistency alone can never give (#280)."""
        cur = self.pg.cursor()
        cur.execute(
            f"SELECT id, project, event_type, content, prev_hash, hash "
            f"FROM {TABLE} ORDER BY created_at ASC"
        )
        rows = cur.fetchall()
        cur.close()
        previous = None
        for record_id, project, event_type, content, prev_hash, stored_hash in rows:
            # A row is intact if its stored hash matches the v2 digest (id +
            # project covered) OR the legacy v1 digest (pre-A7 rows). Both are
            # accepted so the code upgrade doesn't flag an un-migrated chain as
            # tampered; a simple project-column UPDATE on a v2 row still breaks
            # BOTH digests and is caught. Run rechain() to bring v1 rows to v2.
            ok = prev_hash == previous and (
                entry_hash_v2(previous, record_id, project, event_type, content) == stored_hash
                or entry_hash(previous, event_type, content) == stored_hash)
            if not ok:
                return {"valid": False, "broken_at": record_id,
                        "count": len(rows), "head": None}
            previous = stored_hash
        if expected_head is not None and previous != expected_head:
            # Internally consistent but not the chain the caller anchored:
            # exactly what an edit-plus-rechain forgery looks like from
            # outside. broken_at stays None so the two failures are
            # distinguishable.
            return {"valid": False, "broken_at": None, "count": len(rows),
                    "head": previous, "expected_head": expected_head}
        return {"valid": True, "broken_at": None, "count": len(rows),
                "head": previous}

    def rechain(self) -> dict:
        """One-time migration (box audit A7): re-hash every row under v2 so the
        ``id``/``project`` columns become tamper-evident for legacy entries too,
        re-linking prev_hash as it goes. Idempotent — a fully-v2 chain is left
        unchanged. Must run under the same advisory lock as appends.

        Self-documenting (#280): a run that migrated anything appends a
        ``governance.rechain`` row — pre-migration head, rows migrated — so a
        relink leaves a mark IN the chain it relinked. That makes a quiet
        rechain loud; it does not make a malicious one impossible (the
        operator can delete the marker and relink again), which is why
        ``verify(expected_head=...)`` and an externally-held head remain the
        real close. A run that migrated nothing appends nothing, so repeated
        idempotent runs do not grow the chain."""
        cur = self.pg.cursor()
        locked = False
        try:
            cur.execute("SELECT pg_advisory_lock(%s)", (LOCK_KEY,))
            locked = True
            cur.execute(
                f"SELECT id, project, event_type, content, hash "
                f"FROM {TABLE} ORDER BY created_at ASC")
            rows = cur.fetchall()
            pre_head = rows[-1][4] if rows else None
            previous, migrated = None, 0
            for record_id, project, event_type, content, stored_hash in rows:
                digest = entry_hash_v2(previous, record_id, project, event_type, content)
                if digest != stored_hash:
                    cur.execute(
                        f"UPDATE {TABLE} SET prev_hash = %s, hash = %s WHERE id = %s",
                        (previous, digest, record_id))
                    migrated += 1
                previous = digest
            if migrated:
                # Chained onto the walk's own head, under the same lock the
                # walk held — no re-read, no retry loop. Plain %s::jsonb so
                # this stays runnable without psycopg2.extras (and testable
                # against the same fake cursor as the rest of this class).
                marker_id = str(uuid.uuid4())
                marker = {"pre_migration_head": pre_head,
                          "migrated": migrated, "count": len(rows)}
                digest = entry_hash_v2(previous, marker_id, "governance",
                                       "governance.rechain", marker)
                cur.execute(
                    f"INSERT INTO {TABLE} "
                    "(id, project, event_type, content, prev_hash, hash, created_at) "
                    "VALUES (%s, %s, %s, %s::jsonb, %s, %s, clock_timestamp())",
                    (marker_id, "governance", "governance.rechain",
                     json.dumps(marker), previous, digest))
                previous = digest
            self.pg.commit()
            return {"migrated": migrated, "count": len(rows),
                    "pre_head": pre_head, "head": previous}
        finally:
            if locked:
                cur.execute("SELECT pg_advisory_unlock(%s)", (LOCK_KEY,))
            cur.close()

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
        from psycopg2.extras import RealDictCursor
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
