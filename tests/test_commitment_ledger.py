"""
test_commitment_ledger.py — membrane-invariant tests for the Commitment Membrane skeleton.

Mirrors the voice suite: each test asserts one discipline of the outward membrane, driven by
synthetic events and an explicit clock. No network, no models.
Run: python3 -m unittest test_commitment_ledger -v  (or pytest tests/test_commitment_ledger.py)
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta

from willow_mcp.commitments.commitment_ledger import (
    CalendarEvent,
    Commitment,
    CommitmentLedger,
    CommitmentState,
    DewConfig,
    StubCalendarSource,
)

BASE = datetime(2026, 7, 20, 9, 0, 0)   # a fixed Monday morning; all times relative to this


def ev(uid, minutes_from_base, dur_min=30, title="Standup", body="", cancelled=False, who=()):
    start = BASE + timedelta(minutes=minutes_from_base)
    return CalendarEvent(uid=uid, title=title, start=start,
                         end=start + timedelta(minutes=dur_min),
                         attendees=tuple(who), body=body, cancelled=cancelled)


class ReceiptNotRecording(unittest.TestCase):
    def test_sensitive_body_never_stored_or_logged(self):
        secret = "dial-in 555-9999, re: severance terms and the number"
        src = StubCalendarSource([ev("a", 120, title="1:1 w/ legal", body=secret)])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        c = ledger.commitments["a"]
        # the fact is kept…
        self.assertEqual(c.title, "1:1 w/ legal")
        # …but the body is nowhere: no field holds it, and it is not in any receipt.
        forbidden = {"body", "notes", "description", "location", "raw"}
        self.assertEqual(set(vars(c)) & forbidden, set())
        blob = repr(c) + repr(ledger.receipts)
        self.assertNotIn(secret, blob)
        self.assertNotIn("severance", blob)


class StatesNotDeletions(unittest.TestCase):
    def test_cancel_withdraws_but_keeps_record_and_history(self):
        src = StubCalendarSource([ev("a", 120, title="Dentist")])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        src.set_events([ev("a", 120, title="Dentist", cancelled=True)])
        ledger.ingest()
        c = ledger.commitments["a"]                 # still present — never deleted
        self.assertIn("a", ledger.commitments)
        self.assertIs(c.state, CommitmentState.WITHDRAWN)
        reasons = [h.reason for h in c.history]
        self.assertIn("created", reasons)
        self.assertIn("cancelled", reasons)

    def test_reschedule_keeps_old_time_in_history_and_stays_active(self):
        src = StubCalendarSource([ev("a", 120, title="Review")])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        old = ledger.commitments["a"].when
        src.set_events([ev("a", 300, title="Review")])   # moved 3h later
        ledger.ingest()
        c = ledger.commitments["a"]
        self.assertIs(c.state, CommitmentState.ACTIVE)     # a move is still a live commitment
        self.assertEqual(c.when, BASE + timedelta(minutes=300))
        self.assertTrue(any(old.isoformat() in h.reason for h in c.history))  # old time preserved


class DewRuleSilence(unittest.TestCase):
    def test_silent_when_nothing_is_due(self):
        # three normal, acknowledged, non-overlapping future commitments
        src = StubCalendarSource([ev("a", 600), ev("b", 700), ev("c", 800)])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        now = BASE                                        # hours before anything
        self.assertEqual(ledger.dew_surface(now), [], "dew spoke when nothing was due")

    def test_surfaces_imminent(self):
        src = StubCalendarSource([ev("a", 10, title="Call")])   # 10 min out
        ledger = CommitmentLedger(source=src, config=DewConfig(lead=timedelta(minutes=15)))
        ledger.ingest()
        surf = ledger.dew_surface(BASE)
        kinds = {s.kind for s in surf}
        self.assertIn("imminent", kinds)
        self.assertTrue(all("severance" not in s.fact for s in surf))

    def test_surfaces_conflict(self):
        # a and b overlap (both 10:00–10:30-ish)
        src = StubCalendarSource([ev("a", 60, dur_min=60, title="A"),
                                  ev("b", 90, dur_min=60, title="B")])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        surf = ledger.dew_surface(BASE)
        conflicts = [s for s in surf if s.kind == "conflict"]
        self.assertEqual(len(conflicts), 1)
        self.assertEqual(set(conflicts[0].uids), {"a", "b"})

    def test_unacknowledged_change_surfaces_then_goes_silent(self):
        src = StubCalendarSource([ev("a", 600, title="Flight")])
        ledger = CommitmentLedger(source=src)
        ledger.ingest()
        self.assertEqual(ledger.dew_surface(BASE), [])           # baseline: silent
        src.set_events([ev("a", 660, title="Flight")])           # rescheduled
        ledger.ingest()
        mism = [s for s in ledger.dew_surface(BASE) if s.kind == "mismatch"]
        self.assertEqual(len(mism), 1)                           # the change speaks once
        ledger.acknowledge("a")
        self.assertEqual([s for s in ledger.dew_surface(BASE) if s.kind == "mismatch"], [])  # then silent


class NoNewAuthority(unittest.TestCase):
    def test_default_gate_denies_and_ledger_has_no_write_path(self):
        src = StubCalendarSource([ev("a", 120)])
        ledger = CommitmentLedger(source=src)                    # default gate = deny
        ledger.ingest()
        self.assertFalse(ledger.propose_action("a", "cancel"))   # fail-closed
        # the read-only source exposes no mutation surface at all
        for m in ("create", "update", "delete", "write", "save", "put"):
            self.assertFalse(hasattr(src, m), f"read-only source leaked a {m}() method")

    def test_allowed_action_is_gated_not_a_direct_write(self):
        seen = []

        def gate(action, commitment):
            seen.append((action, commitment.uid))
            return action == "reschedule"

        src = StubCalendarSource([ev("a", 120)])
        ledger = CommitmentLedger(source=src, gate_fn=gate)
        ledger.ingest()
        self.assertTrue(ledger.propose_action("a", "reschedule"))
        self.assertFalse(ledger.propose_action("a", "delete"))
        self.assertEqual(seen, [("reschedule", "a"), ("delete", "a")])   # every action hit the gate
        # even the allowed action did not mutate the source events
        self.assertEqual(len(src.fetch()), 1)


class ReceiptHygieneWholeCycle(unittest.TestCase):
    def test_no_receipt_carries_content_across_a_full_cycle(self):
        src = StubCalendarSource([ev("a", 10, title="X", body="secret notes"),
                                  ev("b", 700, title="Y", body="more secrets")])
        ledger = CommitmentLedger(source=src, gate_fn=lambda a, c: True)
        ledger.ingest()
        ledger.propose_action("a", "cancel")
        ledger.acknowledge("a")
        src.set_events([ev("a", 40, title="X"), ev("b", 700, title="Y", cancelled=True)])
        ledger.ingest()
        forbidden = {"body", "notes", "description", "location", "raw"}
        for r in ledger.receipts:
            self.assertEqual(forbidden & r.keys(), set(), f"{r['event']} receipt leaked content")
        self.assertNotIn("secret", repr(ledger.receipts))


if __name__ == "__main__":
    unittest.main(verbosity=2)
