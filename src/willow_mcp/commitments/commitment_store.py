"""
commitment_store.py — persistence for the Commitment Membrane (Jarvis layer 2, Step 4).

Persists commitments + their full state history into fleet state (SOIL/store), IN-NAMESPACE
(`willow/commitments`). The core ledger stays a pure in-memory object; this module is the
imperative-shell seam that carries it to durable storage and back — the real store is an
injected driver (willow-mcp's `_store`), so all serialization discipline is unit-testable
offline against a fake store, with no SQLite and no server.

The whole point of this layer is that persistence CANNOT become recording. Two guards:

  1. RECEIPT-NOT-RECORDING re-enforced at the storage boundary. A serialized commitment carries
     only the FACT (uid / title / when / who / state / acknowledged / history-of-transitions).
     `_assert_no_forbidden` walks the record recursively and refuses any key in
     `_FORBIDDEN_FACT_KEYS` (body/notes/description/location/raw) — the same guard the ledger's
     receipts run, now standing at the door to durable state. A future edit that tries to stash
     an event body fails loudly here, it does not silently persist.
  2. STATES-NOT-DELETIONS preserved on the round trip. History (including a WITHDRAWN state and a
     moved commitment's old time) serializes and rehydrates intact; nothing is dropped.

Read-only-out by inheritance: this layer persists the ledger's record of the calendar; it never
writes the calendar. No new authority is introduced.

Design: willow/design/willow-commitment-membrane.md (Step 4) · pure script, no models. ΔΣ=42
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional, Protocol, runtime_checkable

from willow_mcp.commitments.commitment_ledger import (
    _FORBIDDEN_FACT_KEYS,
    Commitment,
    CommitmentLedger,
    CommitmentState,
    StateChange,
)

DEFAULT_COLLECTION = "willow/commitments"


@runtime_checkable
class RecordStore(Protocol):
    """Minimal store contract — the shape of willow-mcp's `_store`.

    Deliberately narrow: put (create/overwrite by id) and all (read a collection). No delete
    method is required or used — states-not-deletions means we never remove a commitment record,
    only append history and re-put its current state.
    """

    def put(self, collection: str, record: dict, record_id: Optional[str] = None) -> object: ...

    def all(self, collection: str) -> list: ...


def _assert_no_forbidden(record: dict, *, path: str = "record") -> None:
    """Refuse any forbidden (content-bearing) key, at any depth. The storage-boundary mirror of
    CommitmentLedger._receipt's guard. Raises AssertionError — loud, never a silent pass."""
    if isinstance(record, dict):
        leaked = _FORBIDDEN_FACT_KEYS & record.keys()
        if leaked:
            raise AssertionError(
                f"persisted record would leak content via {sorted(leaked)} at {path}"
            )
        for k, v in record.items():
            _assert_no_forbidden(v, path=f"{path}.{k}")
    elif isinstance(record, (list, tuple)):
        for i, v in enumerate(record):
            _assert_no_forbidden(v, path=f"{path}[{i}]")


def _serialize(c: Commitment) -> dict:
    """Commitment -> plain dict of FACTS only. Carries no field that could hold event body."""
    record = {
        "uid": c.uid,
        "title": c.title,
        "when": c.when.isoformat(),
        "end": c.end.isoformat() if c.end else None,
        "who": list(c.who),
        "state": c.state.name,
        "acknowledged": c.acknowledged,
        "history": [
            {
                "tick": h.tick,
                "state": h.state.name,
                "when": h.when.isoformat(),
                "reason": h.reason,
            }
            for h in c.history
        ],
    }
    _assert_no_forbidden(record)  # last line of defense before it leaves the process
    return record


def _deserialize(record: dict) -> Commitment:
    """Plain dict -> Commitment. Reads only known FACT keys; any extra store metadata
    (an injected id, timestamps) is ignored, so a rehydrate never resurrects content."""
    return Commitment(
        uid=record["uid"],
        title=record["title"],
        when=datetime.fromisoformat(record["when"]),
        end=datetime.fromisoformat(record["end"]) if record.get("end") else None,
        who=tuple(record.get("who", ())),
        state=CommitmentState[record["state"]],
        acknowledged=record["acknowledged"],
        history=[
            StateChange(
                tick=h["tick"],
                state=CommitmentState[h["state"]],
                when=datetime.fromisoformat(h["when"]),
                reason=h.get("reason", ""),
            )
            for h in record.get("history", [])
        ],
    )


class CommitmentPersistence:
    """Carries a CommitmentLedger's commitments to durable store and back.

    The store is injected (willow-mcp `_store`, or a fake in tests). The commitment `uid` is the
    record id, so a re-save overwrites the same row in place — states-not-deletions means the
    row's history GROWS across saves; it is never split into new rows or deleted.
    """

    def __init__(self, store: RecordStore, *, collection: str = DEFAULT_COLLECTION):
        self._store = store
        self.collection = collection

    def save(self, commitment: Commitment) -> None:
        self._store.put(self.collection, _serialize(commitment), record_id=commitment.uid)

    def save_ledger(self, ledger: CommitmentLedger) -> None:
        for c in ledger.commitments.values():
            self.save(c)

    def load_all(self) -> dict[str, Commitment]:
        out: dict[str, Commitment] = {}
        for record in self._store.all(self.collection):
            if not isinstance(record, dict) or "uid" not in record:
                continue  # skip non-commitment rows / tombstones defensively
            c = _deserialize(record)
            out[c.uid] = c
        return out

    def restore_into(self, ledger: CommitmentLedger) -> None:
        """Rehydrate persisted commitments into a fresh ledger (e.g. on boot), without
        re-fetching the calendar. Existing in-memory commitments take precedence — a stale
        stored row never overwrites a live one."""
        for uid, c in self.load_all().items():
            ledger.commitments.setdefault(uid, c)
