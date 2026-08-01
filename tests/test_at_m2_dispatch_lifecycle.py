"""AT-M2 — the 2026-07-31 red-team dispatch-lifecycle findings (B-51, B-53;
issues #240, #239), replayed against the current code through the real MCP
tool wrappers (server.*), each step asserting refusal.

  B-53 (dispatch_accept/handoff_write_v4 missing from ORCHESTRATOR_WRITE_TOOLS)
    -> stdio app_id=willow with no WILLOW_HUMAN_ORCHESTRATOR could accept and
       complete a real packet, bypassing session_enter's own "human-only,
       never dispatch entry" guard by calling either tool directly.

  B-51 (dispatch_write over-granting verify_handoff/agent_clear to builders)
    -> a builder seat (dispatch_write only, no orchestrator group) could
       verify_handoff and agent_clear its own forged lifecycle end to end,
       with zero orchestrator/human involvement -- self-certifying its own
       work instead of the orchestrator checking it.
"""
import json

from willow_mcp import server


def _write_manifest(home, app_id, **overrides):
    d = home / "mcp_apps" / app_id
    d.mkdir(parents=True, exist_ok=True)
    data = {"app_id": app_id, "permissions": ["store_read"]}
    data.update(overrides)
    (d / "manifest.json").write_text(json.dumps(data))


def test_b53_willow_cannot_accept_a_dispatch_without_human_env(home, monkeypatch):
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    _write_manifest(home, "willow", permissions=["orchestrator"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("loki", "willow", "# Assignment\n\nDo the thing.\n")
    did = sent["dispatch_id"]

    result = server.dispatch_accept("willow", did)
    assert "error" in result
    assert "orchestrator_human_required" in result["error"]
    assert "dispatch_accept" in result["error"]


def test_b53_willow_cannot_complete_a_dispatch_without_human_env(home, monkeypatch):
    """Independent of accept's own refusal above -- handoff_write_v4 must
    refuse on its own, since a caller could otherwise skip straight to it."""
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    _write_manifest(home, "willow", permissions=["orchestrator"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("loki", "willow", "# Assignment\n\nDo the thing.\n")
    did = sent["dispatch_id"]

    result = server.handoff_write_v4("willow", did, narrative="done")
    assert "error" in result
    assert "orchestrator_human_required" in result["error"]
    assert "handoff_write_v4" in result["error"]


def test_b53_willow_can_accept_and_complete_with_human_env(home, monkeypatch):
    """Sanity: the fix is additive, not a new blanket refusal -- an actually
    attested human orchestrator can still run the dispatch lifecycle."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    _write_manifest(home, "willow", permissions=["orchestrator"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("loki", "willow", "# Assignment\n\nDo the thing.\n")
    did = sent["dispatch_id"]

    accepted = server.dispatch_accept("willow", did)
    assert accepted["status"]["status"] == "working"

    completed = server.handoff_write_v4("willow", did, narrative="done")
    assert completed["status"] == "complete"


def test_b51_builder_cannot_verify_its_own_forged_lifecycle(home):
    _write_manifest(home, "hanuman", permissions=["dispatch_read", "dispatch_write"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("hanuman", "loki", "# Assignment\n\nAudit x.\n")
    did = sent["dispatch_id"]

    accepted = server.dispatch_accept("loki", did)
    assert accepted["status"]["status"] == "working"

    closed = server.handoff_write_v4("loki", did, narrative="done", findings=[])
    assert closed["status"] == "complete"

    result = server.verify_handoff("hanuman", did)
    assert "error" in result
    assert "not permitted for 'verify_handoff'" in result["error"]


def test_b51_builder_cannot_clear_its_own_forged_lifecycle(home):
    _write_manifest(home, "hanuman", permissions=["dispatch_read", "dispatch_write"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("hanuman", "loki", "# Assignment\n\nAudit x.\n")
    did = sent["dispatch_id"]
    server.dispatch_accept("loki", did)
    server.handoff_write_v4("loki", did, narrative="done", findings=[])

    result = server.agent_clear("hanuman", "loki", did)
    assert "error" in result
    assert "not permitted for 'agent_clear'" in result["error"]


def test_b51_orchestrator_can_still_verify_and_clear(home, monkeypatch):
    """Sanity: the fix narrows the builder grant, not the orchestrator one."""
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    _write_manifest(home, "willow", permissions=["orchestrator"])
    _write_manifest(home, "hanuman", permissions=["dispatch_read", "dispatch_write"])
    _write_manifest(home, "loki", permissions=["dispatch_read", "dispatch_write"])

    sent = server.dispatch_send("hanuman", "loki", "# Assignment\n\nAudit x.\n")
    did = sent["dispatch_id"]
    server.dispatch_accept("loki", did)
    server.handoff_write_v4("loki", did, narrative="done", findings=[])

    verified = server.verify_handoff("willow", did)
    assert verified["verified"] is True

    cleared = server.agent_clear("willow", "loki", did)
    assert cleared["status"] == "cleared"
