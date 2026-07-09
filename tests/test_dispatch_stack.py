"""Tests for dispatch packet stack (filesystem under WILLOW_HOME)."""

import json

import pytest

from willow_mcp import dispatch as ds
from willow_mcp import handoff as ho


@pytest.fixture
def orchestrator_app(home):
    apps = home / "mcp_apps" / "willow"
    apps.mkdir(parents=True)
    (apps / "manifest.json").write_text(
        json.dumps({"permissions": ["orchestrator"]})
    )
    return "willow"


def test_dispatch_send_and_read(home):
    md = """# Audit PR #786

## Checklist
- [ ] Read diff
"""
    sent = ds.dispatch_send(
        "willow", "loki", md, role="loki", summary="Audit PR #786"
    )
    assert "dispatch_id" in sent
    did = sent["dispatch_id"]

    pkt = ds.dispatch_read(did)
    assert pkt["meta"]["to_app"] == "loki"
    assert pkt["meta"]["role"] == "loki"
    assert "Audit PR #786" in pkt["assignment"]
    assert pkt["status"]["status"] == "pending"


def test_full_lifecycle(home):
    md = "# Task\n\nDo the audit.\n"
    sent = ds.dispatch_send("willow", "loki", md, role="loki")
    did = sent["dispatch_id"]

    acc = ds.dispatch_accept(did, "loki", session_id="sess-1")
    assert acc["status"]["status"] == "working"

    sess = ds.session_read("loki", "sess-1")
    assert sess["dispatch_id"] == did

    done = ho.handoff_write_v4(
        "loki",
        did,
        findings=[{"id": "g1", "text": "gap found", "severity": "high", "evidence": ["a.py:1"]}],
        narrative="Audited.",
    )
    assert done["status"] == "complete"

    v = ho.verify_handoff(did)
    assert v["verified"] is True
    assert v["status"] == "verified"

    cleared = ds.agent_clear("loki", did, session_id="sess-1")
    assert cleared["status"] == "cleared"

    sess2 = ds.session_read("loki", "sess-1")
    assert sess2["status"] == "idle"


def test_dispatch_list_filter(home):
    ds.dispatch_send("willow", "loki", "# A\n", summary="a")
    ds.dispatch_send("willow", "hanuman", "# B\n", summary="b")
    rows = ds.dispatch_list(to_app="loki")
    assert rows["total"] == 1
    assert rows["dispatches"][0]["to_app"] == "loki"


def test_wrong_recipient_rejected(home):
    sent = ds.dispatch_send("willow", "loki", "# x\n")
    did = sent["dispatch_id"]
    err = ds.dispatch_accept(did, "hanuman")
    assert err.get("error") == "wrong_recipient"


def test_session_enter_human_path(home):
    from willow_mcp import home_init as hi

    hi.ensure_home_layout()
    out = ds.session_enter("hanuman", "sess-human")
    assert out["entry_mode"] == "human"
    assert out["dispatch_id"] is None
    assert "session_handoff_write" in out["closeout_tools"]
    assert out.get("persona")
    assert "Hanuman" in out.get("persona", "") or out.get("display_name") == "Hanuman"
    assert out.get("persona_path") == "personas/hanuman.md"
    sess = ds.session_read("hanuman", "sess-human")
    assert sess["status"] == "idle"
    assert sess["dispatch_id"] == ""


def test_session_enter_dispatch_by_id(home):
    from willow_mcp import home_init as hi

    hi.ensure_home_layout()
    sent = ds.dispatch_send("willow", "loki", "# Build\n\nShip it.\n", summary="build")
    did = sent["dispatch_id"]
    out = ds.session_enter("loki", "sess-disp", dispatch_id=did)
    assert out["entry_mode"] == "dispatch"
    assert out["dispatch_id"] == did
    assert "Ship it" in out["assignment"]
    assert out["status"] == "working"
    assert out["closeout_tools"] == ["handoff_write_v4"]
    assert out.get("persona")
    assert out.get("display_name") == "Loki"


def test_session_enter_picks_pending_packet(home):
    sent = ds.dispatch_send("willow", "ada", "# Monitor\n", summary="watch")
    did = sent["dispatch_id"]
    out = ds.session_enter("ada", "sess-auto")
    assert out["entry_mode"] == "dispatch"
    assert out["dispatch_id"] == did


def test_session_handoff_write_human_closeout(home):
    ds.session_enter("hanuman", "sess-close")
    out = ds.session_handoff_write(
        "hanuman",
        "sess-close",
        narrative="Fixed consent docs.",
        summary="B-33 filed",
        next_bite="kart-sandbox bound_ro",
    )
    assert out["entry_mode"] == "human"
    assert "handoff_path" in out
    from pathlib import Path

    assert Path(out["handoff_path"]).exists()
    sess = ds.session_read("hanuman", "sess-close")
    assert sess["status"] == "idle"
