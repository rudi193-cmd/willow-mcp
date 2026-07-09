"""Human-only orchestrator seat tests."""

import json

import pytest

from willow_mcp import dispatch as ds
from willow_mcp import human_session as hs
from willow_mcp.gate import permitted


# home fixture from tests/conftest.py


def test_session_enter_willow_human_only(home):
    out = ds.session_enter("willow", "sess-orch")
    assert out["entry_mode"] == "human_orchestrator"
    assert out["dispatch_id"] is None
    assert "ORIENT_ORCHESTRATOR" in out["agent_doc"]


def test_session_enter_willow_rejects_dispatch_id(home):
    out = ds.session_enter("willow", "sess-orch", dispatch_id="ABCD1234")
    assert out["error"] == "orchestrator_human_only"


def test_session_enter_willow_ignores_pending_packet(home):
    ds.dispatch_send("willow", "willow", "# Self\n", summary="should not auto-bind")
    out = ds.session_enter("willow", "sess-orch")
    assert out["entry_mode"] == "human_orchestrator"
    assert out.get("dispatch_id") is None


def test_orchestrator_write_denied_without_human_env(home):
    apps = home / "mcp_apps" / "willow"
    apps.mkdir(parents=True)
    (apps / "manifest.json").write_text(
        json.dumps({"permissions": ["orchestrator"]})
    )
    assert permitted("willow", "dispatch_send")
    reason = hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False)
    assert reason is not None
    assert "WILLOW_HUMAN_ORCHESTRATOR" in reason


def test_orchestrator_write_allowed_with_human_env(home, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    assert hs.orchestrator_write_denial("willow", "dispatch_send", serve_mode=False) is None


def test_specialist_write_not_human_gated(home):
    assert hs.orchestrator_write_denial("hanuman", "dispatch_send", serve_mode=False) is None
