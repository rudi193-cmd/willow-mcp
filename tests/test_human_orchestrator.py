"""Human-only orchestrator seat tests."""

import json


from willow_mcp import dispatch as ds
from willow_mcp import human_session as hs
from willow_mcp.gate import permitted


# home fixture from tests/conftest.py


def test_session_enter_willow_human_only(home):
    out = ds.session_enter("willow", "sess-orch")
    assert out["entry_mode"] == "human_orchestrator"
    assert out["dispatch_id"] is None
    assert out["agent_doc"] == "docs/AGENTS.md"
    assert out["agent_doc_section"] == "orchestrator"


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


# ── by_human_attested: the seat claim vs. the seat ───────────────────────────
#
# These are unit-level on purpose: they pin the predicate's own truth table,
# both arms, independent of any caller. The serve arm is ALSO now driven end to
# end — sign-in, confirmed binding, gate, tool body — in test_serve_mode_gate.py,
# which enters serve mode through the server._serve_mode() accessor. That is the
# test the earlier version of this comment said could not be written.

def test_by_human_false_for_unattested_willow_claim(home, monkeypatch):
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    assert hs.by_human_attested("willow", serve_mode=False) is False


def test_by_human_true_only_with_the_host_attestation(home, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    assert hs.by_human_attested("willow", serve_mode=False) is True


def test_by_human_serve_mode_trusts_the_confirmed_binding(home, monkeypatch):
    """In serve mode app_id reaches the tool body only after _gate replaced it
    with the OAuth-bound identity, so 'willow' there means the operator ran
    confirm-binding. No env var is needed — and none is consulted."""
    monkeypatch.delenv("WILLOW_HUMAN_ORCHESTRATOR", raising=False)
    assert hs.by_human_attested("willow", serve_mode=True) is True


def test_by_human_false_for_every_non_willow_app(home, monkeypatch):
    monkeypatch.setenv("WILLOW_HUMAN_ORCHESTRATOR", "1")
    for app in ("hanuman", "", "willow-2", "wíllow"):
        assert hs.by_human_attested(app, serve_mode=False) is False
        assert hs.by_human_attested(app, serve_mode=True) is False
