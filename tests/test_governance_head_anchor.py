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
import pytest

from test_governance_ledger_a7 import ENTRIES, _FakePg, _v1_chain, _v2_chain

from willow_mcp import frank_head_anchor
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


# ── rechain() itself consults the ON-DISK anchor (not just verify()'s
# expected_head parameter) — the actual close for #280's "nothing outside
# the database catches a relink," since this is what runs BEFORE the
# migration that would otherwise launder a tampered row. ─────────────────
@pytest.fixture
def home(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    return tmp_path


def test_rechain_proceeds_unguarded_with_no_anchor_file(home):
    # The default, pre-#280 behavior: an install that never opted into
    # anchoring is not newly broken.
    pg = _FakePg(_v1_chain(ENTRIES))
    out = GovernanceLedger(pg).rechain()
    assert out.get("refused") is not True
    assert out["migrated"] == len(ENTRIES)


def test_rechain_refuses_when_anchor_disagrees_with_the_live_head(home):
    # The issue's exact attack, closed one step earlier than verify(): an
    # operator anchored the chain's honest head, content on one row was
    # then edited (out of band -- not through this class), and now rechain()
    # is asked to run. It must not silently re-hash the tampered row and
    # move on.
    pg = _FakePg(_v1_chain(ENTRIES))
    frank_head_anchor.write_anchor("f" * 64, len(ENTRIES), anchored_by="operator")
    before = [dict(r) for r in pg.rows]

    out = GovernanceLedger(pg).rechain()

    assert out["refused"] is True
    assert out["reason"] == "head_mismatch"
    assert out["anchored_head"] == "f" * 64
    assert out["pre_head"] == pg.rows[-1]["hash"]
    assert pg.rows == before  # not one row touched -- no UPDATE, no marker


def test_rechain_proceeds_when_anchor_matches_the_live_head(home):
    # The legitimate case: the operator's last-confirmed head IS the
    # current head, so the migration is exactly what it claims to be.
    pg = _FakePg(_v1_chain(ENTRIES))
    pre_head = pg.rows[-1]["hash"]
    frank_head_anchor.write_anchor(pre_head, len(ENTRIES), anchored_by="operator")

    out = GovernanceLedger(pg).rechain()

    assert out.get("refused") is not True
    assert out["migrated"] == len(ENTRIES)
    assert out["pre_head"] == pre_head


def test_rechain_force_overrides_a_mismatched_anchor(home):
    # The explicit operator override, for when re-anchoring first isn't
    # practical -- force is opt-in per call, never a default.
    pg = _FakePg(_v1_chain(ENTRIES))
    frank_head_anchor.write_anchor("f" * 64, len(ENTRIES), anchored_by="operator")

    out = GovernanceLedger(pg).rechain(force=True)

    assert out.get("refused") is not True
    assert out["migrated"] == len(ENTRIES)


def test_rechain_refuses_on_an_untrusted_anchor_file_rather_than_ignoring_it(home):
    # A file that EXISTS but fails the trust check is an anomaly, not the
    # same as "no anchor configured" -- falling back to unguarded here is
    # exactly the gap a local attacker who can loosen permissions would
    # reach for.
    pg = _FakePg(_v1_chain(ENTRIES))
    pre_head = pg.rows[-1]["hash"]
    p = frank_head_anchor.write_anchor(pre_head, len(ENTRIES))
    p.chmod(0o666)

    out = GovernanceLedger(pg).rechain()

    assert out["refused"] is True
    assert out["reason"] == "untrusted"


def test_rechain_refuses_on_a_corrupt_anchor_file_rather_than_ignoring_it(home):
    d = home / "constitutional"
    d.mkdir(parents=True)
    (d / "frank_head_anchor.json").write_text("{not json")
    (d / "frank_head_anchor.json").chmod(0o600)
    pg = _FakePg(_v1_chain(ENTRIES))

    out = GovernanceLedger(pg).rechain()

    assert out["refused"] is True
    assert out["reason"] == "unreadable"
