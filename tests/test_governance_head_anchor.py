"""#280 — the head anchor: "is this the same chain it was yesterday?"

The finding, pinned as a test before anything else: *edit a row, run
rechain()* produces a chain ``verify()`` calls valid — the migration and the
forgery are the same operation. Then the two closes this repo now carries:

* ``verify(expected_head=...)`` — an externally-held head detects the
  relink, and the failure is distinguishable from a broken chain;
* a migrating ``rechain()`` appends a ``governance.rechain`` marker
  recording the pre-migration head, so a quiet relink stops being quiet.

The marker is honestly bounded: it raises the cost of a silent relink, it
does not stop a determined DB operator (delete the marker, relink again) —
only the external anchor does. That bound is written in the module
docstring, which is close (1) of the issue.

Same pure fake-cursor harness as test_governance_ledger_a7 — no Postgres.
"""
from test_governance_ledger_a7 import ENTRIES, _FakePg, _v1_chain, _v2_chain

from willow_mcp.governance_ledger import GovernanceLedger


def test_the_finding_edit_plus_rechain_verifies_internally():
    # The issue's exact sequence, kept as a permanent reminder of WHY the
    # anchor exists: without expected_head, the forgery is invisible.
    pg = _FakePg(_v2_chain(ENTRIES))
    led = GovernanceLedger(pg)
    pg.rows[1]["content"] = {"n": "attacker"}
    assert led.verify()["valid"] is False          # tamper alone is caught...
    led.rechain()
    assert led.verify()["valid"] is True           # ...rechain launders it.


def test_expected_head_detects_the_relink():
    pg = _FakePg(_v2_chain(ENTRIES))
    led = GovernanceLedger(pg)
    anchored = led.verify()["head"]                # held OUTSIDE the database
    assert anchored == pg.rows[-1]["hash"]

    pg.rows[1]["content"] = {"n": "attacker"}
    led.rechain()
    report = led.verify(expected_head=anchored)
    assert report["valid"] is False
    # Distinguishable from a broken chain: internally consistent, wrong chain.
    assert report["broken_at"] is None
    assert report["expected_head"] == anchored
    assert report["head"] != anchored


def test_expected_head_passes_on_the_unchanged_chain():
    led = GovernanceLedger(_FakePg(_v2_chain(ENTRIES)))
    anchored = led.verify()["head"]
    report = led.verify(expected_head=anchored)
    assert report["valid"] is True and report["head"] == anchored


def test_migrating_rechain_leaves_a_marker_in_the_chain():
    pg = _FakePg(_v1_chain(ENTRIES))
    led = GovernanceLedger(pg)
    pre_head = pg.rows[-1]["hash"]
    out = led.rechain()

    assert len(pg.rows) == len(ENTRIES) + 1
    marker = pg.rows[-1]
    assert marker["event_type"] == "governance.rechain"
    assert marker["content"]["pre_migration_head"] == pre_head
    assert marker["content"]["migrated"] == len(ENTRIES)
    assert out["pre_head"] == pre_head
    assert out["head"] == marker["hash"]
    # The marker rides the chain it documents: the whole thing verifies,
    # and the returned head IS the anchor to hold for next time.
    report = led.verify(expected_head=out["head"])
    assert report["valid"] is True


def test_verify_always_reports_the_head_to_anchor():
    led = GovernanceLedger(_FakePg(_v2_chain(ENTRIES)))
    assert led.verify()["head"] == led.verify()["head"] != None  # noqa: E711
    empty = GovernanceLedger(_FakePg([]))
    report = empty.verify()
    assert report["valid"] is True and report["head"] is None
