"""
test_calendar_source_gcal.py — mapping invariants for GCalSyncSource (Jarvis layer 2, Step 2).

Verifies the Google Calendar v3 event JSON -> CalendarEvent mapping offline: no network, no
OAuth, no gcal-sync dep. Fixtures are the documented v3 `events` resource shape. The transport
is exercised only through an injected `list_events`, so the whole suite runs on the documented
JSON contract, not a live account.
Run: python3 -m unittest test_calendar_source_gcal -v  →  11/11 pass.
"""
from __future__ import annotations

import unittest

from willow_mcp.commitments.calendar_source import GCalSyncSource

# Google Calendar v3 `events` fixtures (documented resource shape).
TIMED = {
    "id": "abc123", "summary": "Schmidt grant sync", "status": "confirmed",
    "start": {"dateTime": "2026-07-18T15:00:00-06:00"},
    "end":   {"dateTime": "2026-07-18T15:30:00-06:00"},
    "attendees": [{"email": "a@x.io"}, {"email": "b@y.org"}],
    "description": "SENSITIVE body the ledger must drop",
}
ALLDAY = {"id": "d1", "summary": "Focus day", "status": "confirmed",
          "start": {"date": "2026-07-20"}, "end": {"date": "2026-07-21"}}
CANCELLED = {"id": "c1", "summary": "Dropped", "status": "cancelled",
             "start": {"dateTime": "2026-07-19T09:00:00Z"}}
ZULU = {"id": "z1", "summary": "UTC mtg", "status": "confirmed",
        "start": {"dateTime": "2026-07-19T09:00:00Z"}}
UNTITLED = {"id": "u1", "status": "confirmed", "start": {"dateTime": "2026-07-19T10:00:00-06:00"}}


class TestGCalSyncSource(unittest.TestCase):
    def test_timed_core_fact(self):
        e = GCalSyncSource._map(TIMED)
        self.assertEqual(e.uid, "abc123")
        self.assertEqual(e.title, "Schmidt grant sync")
        self.assertEqual(e.start.hour, 15)
        self.assertFalse(e.cancelled)

    def test_attendees_from_email(self):
        self.assertEqual(GCalSyncSource._map(TIMED).attendees, ("a@x.io", "b@y.org"))

    def test_body_read_but_is_ledgers_to_drop(self):
        # the adapter carries body faithfully; receipt-not-recording is the LEDGER's job (mirror caldav)
        self.assertIn("SENSITIVE", GCalSyncSource._map(TIMED).body)

    def test_allday_date_only_parses(self):
        e = GCalSyncSource._map(ALLDAY)
        self.assertEqual((e.start.year, e.start.month, e.start.day), (2026, 7, 20))
        self.assertEqual(e.start.hour, 0)

    def test_cancelled_status(self):
        self.assertTrue(GCalSyncSource._map(CANCELLED).cancelled)

    def test_zulu_suffix_parses(self):
        self.assertEqual(GCalSyncSource._map(ZULU).start.utcoffset().total_seconds(), 0)

    def test_untitled_event(self):
        self.assertEqual(GCalSyncSource._map(UNTITLED).title, "")

    def test_no_attendees(self):
        self.assertEqual(GCalSyncSource._map(ALLDAY).attendees, ())

    def test_fetch_via_injected_transport_no_network(self):
        src = GCalSyncSource(list_events=lambda s, e: [TIMED, ALLDAY, CANCELLED])
        out = src.fetch()
        self.assertEqual([c.uid for c in out], ["abc123", "d1", "c1"])
        self.assertTrue(out[2].cancelled)

    def test_read_only_no_mutation_methods(self):
        for verb in ("create", "update", "delete", "insert", "patch", "write"):
            self.assertFalse(hasattr(GCalSyncSource, verb), f"read-only violated: {verb}")

    def test_default_transport_fails_loud_not_silent(self):
        # an unconfigured default transport must raise on fetch(), never silently no-op
        with self.assertRaises(NotImplementedError):
            GCalSyncSource().fetch()


if __name__ == "__main__":
    unittest.main(verbosity=2)
