"""
test_commitment_store.py — persistence-layer invariants for the Commitment Membrane (Step 4).

Mirrors ReceiptHygieneWholeCycle at the STORAGE boundary: after a full
ingest -> propose -> ack -> re-ingest cycle, nothing persisted may carry a forbidden
(content-bearing) key, and the round trip must preserve states-not-deletions (a WITHDRAWN state
and a moved commitment's old time survive save+load). No network, no SQLite, no server — the
store is an injected in-memory fake.
Run: python3 -m unittest test_commitment_store -v  (or pytest tests/test_commitment_store.py)
"""
from __future__ import annotations

import json
import unittest
from datetime import datetime, timedelta

from willow_mcp.commitments.commitment_ledger import (
    CalendarEvent,
    CommitmentLedger,
    CommitmentState,
    StubCalendarSource,
)
from willow_mcp.commitments.commitment_store import (
    CommitmentPersistence,
    _assert_no_forbidden,
    _deserialize,
    _serialize,
)

BASE = datetime(2026, 7, 20, 9, 0, 0)
_FORBIDDEN = {"body", "notes", "description", "location", "raw"}


def ev(uid, minutes_from_base, dur_min=30, title="Standup", body="", cancelled=False, who=()):
    start = BASE + timedelta(minutes=minutes_from_base)
    return CalendarEvent(uid=uid, title=title, start=start,
                         end=start + timedelta(minutes=dur_min),
                         attendees=tuple(who), body=body, cancelled=cancelled)


class FakeStore:
    """Minimal in-memory RecordStore — put (overwrite by id) + all (read collection)."""

    def __init__(self):
        self.data: dict[str, dict[str, dict]] = {}

    def put(self, collection, record, record_id=None, deviation=0.0):
        rid = record_id or record.get("uid")
        self.data.setdefault(collection, {})[rid] = dict(record)
        return rid, "created"

    def all(self, collection):
        return list(self.data.get(collection, {}).values())


def _driven_ledger():
    """A ledger driven through a full cycle: create (w/ bodies) -> propose -> ack ->
    re-ingest that cancels one and moves the other."""
    src = StubCalendarSource([
        ev("a", 120, title="1:1 w/ legal", body="dial-in 555, severance terms"),
        ev("b", 700, title="Flight", body="confirmation ABC123, seat 4F"),
    ])
    ledger = CommitmentLedger(source=src, gate_fn=lambda action, c: True)
    ledger.ingest()
    ledger.propose_action("a", "reschedule")
    ledger.acknowledge("a")
    src.set_events([
        ev("a", 180, title="1:1 w/ legal"),               # moved 1h later (stays ACTIVE)
        ev("b", 700, title="Flight", cancelled=True),      # cancelled (WITHDRAWN, kept)
    ])
    ledger.ingest()
    return ledger


class PersistenceReceiptHygiene(unittest.TestCase):
    def test_no_persisted_record_carries_content_across_a_full_cycle(self):
        ledger = _driven_ledger()
        store = FakeStore()
        CommitmentPersistence(store).save_ledger(ledger)
        blob = json.dumps(store.data)
        # no forbidden key anywhere in the persisted structure…
        for collection in store.data.values():
            for record in collection.values():
                _assert_no_forbidden(record)  # raises if any forbidden key at any depth
        # …and none of the sensitive body text leaked into storage
        self.assertNotIn("severance", blob)
        self.assertNotIn("555", blob)
        self.assertNotIn("ABC123", blob)
        self.assertNotIn("seat 4F", blob)

    def test_serialize_guard_rejects_injected_forbidden_key(self):
        # defense-in-depth: if a future edit stuffs a body into a nested structure, the
        # storage-boundary guard must raise, not persist it.
        with self.assertRaises(AssertionError):
            _assert_no_forbidden({"uid": "x", "history": [{"tick": 1, "body": "leak"}]})


class PersistenceRoundTrip(unittest.TestCase):
    def test_states_and_history_survive_save_and_load(self):
        ledger = _driven_ledger()
        store = FakeStore()
        CommitmentPersistence(store).save_ledger(ledger)

        loaded = CommitmentPersistence(store).load_all()
        self.assertEqual(set(loaded), {"a", "b"})

        # 'a' moved but stays ACTIVE, and its old time is preserved in history
        a = loaded["a"]
        self.assertIs(a.state, CommitmentState.ACTIVE)
        self.assertEqual(a.when, BASE + timedelta(minutes=180))
        self.assertTrue(any("moved from" in h.reason for h in a.history))

        # 'b' cancelled -> WITHDRAWN, record kept, history retains created + cancelled
        b = loaded["b"]
        self.assertIs(b.state, CommitmentState.WITHDRAWN)
        reasons = [h.reason for h in b.history]
        self.assertIn("created", reasons)
        self.assertIn("cancelled", reasons)

    def test_reload_into_fresh_ledger_reproduces_dew_behavior(self):
        # persistence must not change what the dew rule decides: a rehydrated ledger surfaces
        # the same mismatch/withdrawn state as the live one.
        ledger = _driven_ledger()
        store = FakeStore()
        CommitmentPersistence(store).save_ledger(ledger)

        fresh = CommitmentLedger(source=StubCalendarSource([]))
        CommitmentPersistence(store).restore_into(fresh)
        # 'b' was cancelled and never acknowledged -> it surfaces as a mismatch after reload
        mism = [s for s in fresh.dew_surface(BASE) if s.kind == "mismatch"]
        self.assertIn("b", {u for s in mism for u in s.uids})
        # and no surfaced fact carries body content
        self.assertTrue(all("severance" not in s.fact for s in fresh.dew_surface(BASE)))

    def test_re_save_overwrites_same_row_states_not_deletions(self):
        # saving twice must keep ONE row per uid whose history has grown — not split rows,
        # not a deleted row.
        ledger = _driven_ledger()
        store = FakeStore()
        p = CommitmentPersistence(store)
        p.save_ledger(ledger)
        first_hist_len = len(store.data["willow/commitments"]["a"]["history"])
        ledger.acknowledge("a")           # one more history entry
        p.save_ledger(ledger)
        rows = store.data["willow/commitments"]
        self.assertEqual(len([k for k in rows if k == "a"]), 1)   # still one 'a' row
        self.assertGreater(len(rows["a"]["history"]), first_hist_len)  # history grew


if __name__ == "__main__":
    unittest.main(verbosity=2)
