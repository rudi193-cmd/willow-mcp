"""frank_verify (MCP tool) wiring to the external head anchor (#280).

GovernanceLedger.verify()'s expected_head plumbing and rechain()'s on-disk
guard are covered in test_governance_head_anchor.py at the class level; this
file is the one hop up -- the actual tool an operator or agent calls folds
the anchor in automatically, and reports which of the anchor's states
applied rather than silently treating "couldn't check" as "checked and
fine."
"""
import json

import pytest
from test_governance_ledger_a7 import ENTRIES, _FakePg, _v2_chain

from willow_mcp import frank_head_anchor, server


@pytest.fixture(autouse=True)
def _fresh_rate_buckets():
    server._buckets.clear()
    yield
    server._buckets.clear()


@pytest.fixture
def app_id(tmp_path, monkeypatch):
    tmp_path.chmod(0o700)
    apps_root = tmp_path / "mcp_apps"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    app_dir = apps_root / "testapp"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(json.dumps({"permissions": ["full_access"]}))
    return "testapp"


def test_frank_verify_reports_unanchored_when_no_anchor_file(app_id, monkeypatch):
    pg = _FakePg(_v2_chain(ENTRIES))
    monkeypatch.setattr(server, "get_pg", lambda: pg)

    result = server.frank_verify(app_id=app_id)

    assert result["valid"] is True
    assert result["anchor_status"] == "unanchored"
    assert "expected_head" not in result  # anchor never entered the comparison


def test_frank_verify_passes_when_anchor_matches_db_head(app_id, monkeypatch):
    pg = _FakePg(_v2_chain(ENTRIES))
    monkeypatch.setattr(server, "get_pg", lambda: pg)
    true_head = pg.rows[-1]["hash"]
    frank_head_anchor.write_anchor(true_head, len(ENTRIES), anchored_by="op")

    result = server.frank_verify(app_id=app_id)

    assert result["valid"] is True
    assert result["anchor_status"] == "anchored"
    assert result["head"] == true_head
    assert "anchor_recorded_at" in result


def test_frank_verify_catches_a_relink_the_anchor_disagrees_with(app_id, monkeypatch):
    # The issue's forgery, end to end: content edited, then rechain()'d
    # (simulated directly on the fake rows, mirroring what rechain() does),
    # leaving a chain that is internally valid but is not the chain the
    # operator anchored.
    from willow_mcp.governance_ledger import GovernanceLedger

    pg = _FakePg(_v2_chain(ENTRIES))
    honest_head = pg.rows[-1]["hash"]
    frank_head_anchor.write_anchor(honest_head, len(ENTRIES), anchored_by="op")

    pg.rows[1]["content"] = {"n": "attacker"}
    monkeypatch.setattr(server, "get_pg", lambda: pg)
    GovernanceLedger(pg).rechain(force=True)  # operator-invoked, not through the tool

    result = server.frank_verify(app_id=app_id)

    assert result["valid"] is False
    assert result["broken_at"] is None          # internally consistent...
    assert result["anchor_status"] == "anchored"
    assert result["expected_head"] == honest_head
    assert result["head"] != honest_head          # ...but not the anchored chain


def test_frank_verify_reports_untrusted_rather_than_silently_skipping(app_id, monkeypatch):
    pg = _FakePg(_v2_chain(ENTRIES))
    monkeypatch.setattr(server, "get_pg", lambda: pg)
    path = frank_head_anchor.write_anchor(pg.rows[-1]["hash"], len(ENTRIES))
    path.chmod(0o666)

    result = server.frank_verify(app_id=app_id)

    # Internal consistency still reported -- read-only tool, does not refuse
    # to answer -- but the anchor comparison visibly did NOT happen.
    assert result["valid"] is True
    assert result["anchor_status"] == "untrusted"
    assert "expected_head" not in result
