"""Graduated announcement volume (willow-gate seam Phase 5) as tested code.

The policy is pure: given a bound trust tier and an outcome, it decides how loudly
to surface a decision on the operator log — louder for the less trusted, always
loud for a denial/discrepancy — without ever being a second audit log.
"""
import logging

import pytest

from willow_mcp import announce
from willow_mcp.receipts import ReceiptLog


@pytest.fixture(autouse=True)
def _on(monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_ANNOUNCE", "1")
    monkeypatch.setenv("WILLOW_MCP_AUDIT_LEVEL", "full")
    announce.set_sink(None)                      # default sink
    yield
    announce.set_sink(None)


# ── the switch ────────────────────────────────────────────────────────────────

def test_off_by_default_is_silent(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_ANNOUNCE", raising=False)
    assert announce.enabled() is False
    assert announce.announce("a", "store_get", "ok", 0) is None


# ── graduated by trust: louder for the less trusted ───────────────────────────

def test_volume_is_louder_for_less_trusted():
    vols = [announce.volume(t, "ok") for t in (4, 3, 2, 1, 0)]
    assert vols == sorted(vols)                  # Elder→Exiled is non-decreasing
    assert announce.volume(4, "ok") == announce.SILENT
    assert announce.volume(0, "ok") == announce.ALERT


def test_unbound_caller_is_loud_not_silent():
    assert announce.volume(None, "ok") == announce.HIGH


def test_elder_ok_is_suppressed_but_untrusted_ok_is_announced():
    assert announce.announce("elder", "store_get", "ok", 4) is None
    assert announce.announce("rookie", "store_get", "ok", 1) == announce.HIGH


# ── denials/discrepancies escalate for everyone ───────────────────────────────

def test_denial_is_alert_even_for_elder():
    assert announce.volume(4, "denied") == announce.ALERT
    assert announce.announce("elder", "store_put", "denied", 4) == announce.ALERT


def test_reconcile_discrepancy_escalates():
    assert announce.volume(3, "reconcile_discrepancy") == announce.ALERT


def test_soft_failure_floor_is_high():
    assert announce.volume(4, "error") == announce.HIGH
    assert announce.volume(4, "rate_limited") == announce.HIGH


def test_credential_returned_is_alert_even_for_elder():
    # A real secret leaving the box under an exemption must never be silent.
    assert announce.volume(4, "credential_returned") == announce.ALERT
    assert announce.announce("elder", "integration_call", "credential_returned", 4) == announce.ALERT


# ── mechanism receipts are never announced (no double lines) ──────────────────

@pytest.mark.parametrize("outcome", ["bind_observed", "bind_enforced"])
def test_binding_mechanism_receipts_are_muted(outcome):
    assert announce.announce("a", "store_get", outcome, 0) is None


# ── audit_level minimal keeps only the loud stuff ─────────────────────────────

def test_minimal_suppresses_routine_but_keeps_denials(monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_AUDIT_LEVEL", "minimal")
    assert announce.announce("steady", "store_put", "ok", 2) is None   # NORMAL < HIGH
    assert announce.announce("steady", "store_put", "denied", 2) == announce.ALERT
    assert announce.announce("rookie", "store_get", "ok", 1) == announce.HIGH  # untrusted still heard


# ── the sink and the log channel ──────────────────────────────────────────────

def test_default_sink_logs_at_graduated_level(caplog):
    with caplog.at_level(logging.DEBUG, logger="willow_mcp.announce"):
        announce.announce("elder", "store_put", "denied", 4)          # ALERT → ERROR
    rec = [r for r in caplog.records if "denied" in r.getMessage()]
    assert rec and rec[0].levelno == logging.ERROR


def test_custom_sink_receives_structured_record():
    seen = []
    announce.set_sink(seen.append)
    announce.announce("x", "task_submit", "ok", 0, detail="d")
    assert seen and seen[0]["tool"] == "task_submit" and seen[0]["volume"] == announce.ALERT
    assert "detail=d" in seen[0]["message"]


def test_sink_failure_never_raises():
    def _boom(_):
        raise RuntimeError("sink down")
    announce.set_sink(_boom)
    # must not propagate — an announcement can never break the caller
    assert announce.announce("x", "store_get", "denied", 0) == announce.ALERT


# ── the ReceiptLog hook fires once per record and cannot break the write ──────

def test_receiptlog_on_record_hook_fires(tmp_path):
    seen = []
    log = ReceiptLog(str(tmp_path / "r.db"), on_record=lambda *a: seen.append(a))
    log.record("me", "store_get", "ok", None)
    assert seen == [("me", "store_get", "ok", None)]


def test_receiptlog_write_survives_a_broken_hook(tmp_path):
    def _boom(*_):
        raise RuntimeError("hook down")
    log = ReceiptLog(str(tmp_path / "r.db"), on_record=_boom)
    log.record("me", "store_get", "ok", None)    # must not raise
    assert log.tail("me")[0]["tool"] == "store_get"   # and the row is still written
