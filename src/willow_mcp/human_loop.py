"""human_loop — the human-in-the-loop primitives: an attention queue and a
durable attestation record.

Ported from willow-2.0's `core/human_required.py` + `core/human_attestation.py`
(migration shortlist §6). Two capabilities, one discipline — *automation pauses
for a human, and the human's sign-off is on the record*:

  - **human_required queue** — an agent enqueues work that must stop automation
    until a person acts (a consent ask, a review, an overload signal). Read /
    enqueue / resolve.
  - **human_attestation** — a durable record that a decision was signed off
    (a KB atom, an edge, a queue item). List / create / check.

Two deliberate departures from the willow-2.0 original:

  1. **SOIL, not the fleet Postgres.** willow-2.0 backs these with Postgres
     tables (`human_required`, `human_attestations`) and `core.pg_bridge`.
     Porting that verbatim would drag a schema migration into the *shared fleet
     database* — the operator-gated act willow-mcp refuses to take unilaterally
     (B-28). These are durable key-by-id records, exactly what the SOIL store is
     for (where gaps, lineage, and commitments already live), so the port homes
     them there. The store is injected, so the logic is unit-testable offline.

  2. **`attested_by` is not forgeable.** The original took `attested_by` as a
     free parameter defaulting to `"operator"` — so an agent could write a record
     claiming the operator attested when they did not. Here the attester is
     ALWAYS the calling identity, and a non-forgeable `by_human` flag records
     whether that identity is the human-orchestrator seat. You can only attest as
     yourself; `has_attestation(require_human=True)` is the gate for the strong
     "a human signed this" case.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Optional

# ── attestation vocabulary ──────────────────────────────────────────────────────
ATTEST_COLLECTION = "human_attestations"
SUBJECT_TYPES = ("knowledge_atom", "edge", "queue_item", "external_review", "other")
ATTEST_STATUSES = ("attested", "rejected", "needs_changes")

# ── queue vocabulary ────────────────────────────────────────────────────────────
QUEUE_COLLECTION = "human_required"
QUEUE_KINDS = ("consent", "attestation", "review", "overload", "onboarding")
QUEUE_OPEN = "open"
QUEUE_RESOLUTIONS = ("resolved", "dismissed", "acknowledged")
QUEUE_STATUSES = (QUEUE_OPEN, *QUEUE_RESOLUTIONS)
PRIORITIES = ("low", "normal", "high", "urgent")


class HumanLoopError(Exception):
    """Bad input to a human-loop primitive (unknown vocab, missing required field)."""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _gen_id() -> str:
    return str(uuid.uuid4())[:8].lower()


def _clean(record: dict) -> dict:
    """Drop the store's injected metadata (_id/_created/…) so a re-put stays a
    clean fact record and a round trip never resurrects store bookkeeping."""
    return {k: v for k, v in record.items() if not k.startswith("_")}


# ── attestation ─────────────────────────────────────────────────────────────────

def create_attestation(
    store,
    *,
    subject_id: str,
    attested_by: str,
    by_human: bool,
    subject_type: str = "knowledge_atom",
    statement: str = "",
    status: str = "attested",
    evidence_ref: str = "",
    context: Optional[dict] = None,
) -> dict:
    """Write a durable attestation/rejection/change-request record.

    `attested_by` and `by_human` are supplied by the binding from the CALLER's
    identity, never by the caller as free text — that is the anti-forgery
    property. Raises HumanLoopError on unknown subject_type/status or empty
    subject_id."""
    subject_id = (subject_id or "").strip()
    if not subject_id:
        raise HumanLoopError("subject_id is required")
    st = (subject_type or "knowledge_atom").strip().lower()
    if st not in SUBJECT_TYPES:
        raise HumanLoopError(f"invalid subject_type {st!r}; expected one of {SUBJECT_TYPES}")
    status = (status or "attested").strip().lower()
    if status not in ATTEST_STATUSES:
        raise HumanLoopError(f"invalid status {status!r}; expected one of {ATTEST_STATUSES}")
    rid = _gen_id()
    record = {
        "id": rid,
        "subject_id": subject_id,
        "subject_type": st,
        "status": status,
        "attested_by": attested_by,
        "by_human": bool(by_human),
        "statement": statement or "",
        "evidence_ref": evidence_ref or "",
        "context": context or {},
        "created_at": _now(),
    }
    store.put(ATTEST_COLLECTION, record, record_id=rid)
    return record


def list_attestations(
    store,
    *,
    subject_id: str = "",
    subject_type: str = "",
    status: str = "",
    limit: int = 50,
) -> list[dict]:
    """Newest-first attestation records, optionally filtered."""
    rows = [_clean(r) for r in store.all(ATTEST_COLLECTION)
            if isinstance(r, dict) and "id" in r]
    if subject_id:
        rows = [r for r in rows if r.get("subject_id") == subject_id]
    if subject_type:
        rows = [r for r in rows if r.get("subject_type") == subject_type.strip().lower()]
    if status:
        rows = [r for r in rows if r.get("status") == status.strip().lower()]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[:max(0, limit)]


def has_attestation(
    store,
    *,
    subject_id: str,
    subject_type: str = "knowledge_atom",
    require_human: bool = False,
) -> bool:
    """True if `subject_id` carries an `attested` record. With require_human, only
    a record `by_human` (the human-orchestrator seat) counts — the gate for
    'a person signed this', immune to an agent self-attesting."""
    subject_id = (subject_id or "").strip()
    if not subject_id:
        return False
    for r in list_attestations(store, subject_id=subject_id, subject_type=subject_type):
        if r.get("status") == "attested" and (not require_human or r.get("by_human") is True):
            return True
    return False


# ── the human-required queue ─────────────────────────────────────────────────────

def enqueue(
    store,
    *,
    kind: str,
    title: str,
    source_agent: str,
    summary: str = "",
    priority: str = "normal",
    source_ref: str = "",
    assignee: str = "",
) -> dict:
    """Enqueue work that must pause automation until a human acts."""
    k = (kind or "").strip().lower()
    if k not in QUEUE_KINDS:
        raise HumanLoopError(f"invalid kind {k!r}; expected one of {QUEUE_KINDS}")
    if not (title or "").strip():
        raise HumanLoopError("title is required")
    pr = (priority or "normal").strip().lower()
    if pr not in PRIORITIES:
        raise HumanLoopError(f"invalid priority {pr!r}; expected one of {PRIORITIES}")
    rid = _gen_id()
    item = {
        "id": rid,
        "kind": k,
        "title": title.strip(),
        "summary": summary or "",
        "priority": pr,
        "status": QUEUE_OPEN,
        "source_agent": source_agent,
        "source_ref": source_ref or "",
        "assignee": assignee or "",
        "created_at": _now(),
        "resolved_by": "",
        "resolved_at": "",
        "note": "",
    }
    store.put(QUEUE_COLLECTION, item, record_id=rid)
    return item


def resolve(store, item_id: str, *, resolved_by: str, status: str = "resolved", note: str = "") -> dict:
    """Resolve / dismiss / acknowledge a queue item. States-not-deletions: the row
    is updated in place with who/when/note, never removed."""
    st = (status or "resolved").strip().lower()
    if st not in QUEUE_RESOLUTIONS:
        raise HumanLoopError(f"invalid status {st!r}; expected one of {QUEUE_RESOLUTIONS}")
    existing = store.get(QUEUE_COLLECTION, item_id)
    if not existing:
        return {"error": "unknown_item", "item_id": item_id}
    item = _clean(existing)
    item.update(status=st, resolved_by=resolved_by, resolved_at=_now(), note=note or "")
    store.put(QUEUE_COLLECTION, item, record_id=item_id)
    return item


def list_queue(store, *, status: str = QUEUE_OPEN, kind: str = "", limit: int = 20) -> list[dict]:
    """Newest-first queue items. `status` defaults to 'open'; pass '' for all."""
    rows = [_clean(r) for r in store.all(QUEUE_COLLECTION)
            if isinstance(r, dict) and "id" in r]
    if status:
        rows = [r for r in rows if r.get("status") == status.strip().lower()]
    if kind:
        rows = [r for r in rows if r.get("kind") == kind.strip().lower()]
    rows.sort(key=lambda r: r.get("created_at", ""), reverse=True)
    return rows[:max(0, limit)]


def queue_stats(store) -> dict[str, int]:
    """Counts by status across the whole queue (unfiltered)."""
    stats: dict[str, int] = {}
    for r in store.all(QUEUE_COLLECTION):
        if isinstance(r, dict) and "id" in r:
            s = r.get("status", "open")
            stats[s] = stats.get(s, 0) + 1
    return stats
