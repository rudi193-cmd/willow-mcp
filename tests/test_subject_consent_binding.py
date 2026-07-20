"""The willow-mcp binding over the stdlib-only guardian-consent core.

The core is blind — stdlib-only, owner-agnostic, no willow audit. This binding
supplies the three facts the core deferred to it: who the owner is (exemption),
the AND-composed gate, and the operator-only mutation seat. Each has a section.
"""
import hashlib

import pytest

from willow_mcp import subject_consent_binding as binding
from willow_mcp.subject_consent import core


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_OWNER_SUBJECT_ID", raising=False)
    monkeypatch.setenv("WILLOW_MCP_RECEIPT_DB", str(tmp_path / "receipt.db"))
    # a fresh ReceiptLog pointed at the isolated db
    monkeypatch.setattr(binding, "_receipts", _NullReceipts())
    return tmp_path


class _NullReceipts:
    """Swallow receipt writes in tests without touching a real db."""
    def __init__(self):
        self.records = []

    def record(self, app_id, tool, outcome, detail=None):
        self.records.append((app_id, tool, outcome, detail))


# ── the registry is internally consistent ─────────────────────────────────────

def test_every_mapped_scope_is_a_real_scope():
    for tool, scope in binding.TOOL_SUBJECT_SCOPE.items():
        assert scope in core.SCOPES, f"{tool} maps to unknown scope {scope!r}"


def test_required_scope_none_for_unlisted_tool():
    assert binding.required_scope("store_get") is None


def test_required_scope_for_listed_tool():
    assert binding.required_scope("nest_promote") == "kb_promotion"


# ── the gate: composed by AND, owner-exempt, fail-closed ───────────────────────

def test_gate_passes_for_non_subject_tool(home):
    assert binding.subject_gate("app", "store_get", "subj-1") is None


def test_gate_passes_when_no_subject_named(home):
    # the tool is subject-scoped but this call carries no subject
    assert binding.subject_gate("app", "nest_promote", None) is None
    assert binding.subject_gate("app", "nest_promote", "   ") is None


def test_gate_denies_non_owner_subject_without_grant(home):
    err = binding.subject_gate("app", "nest_promote", "subj-1")
    assert err is not None
    assert err["code"] == "subject_consent_denied"
    assert err["scope"] == "kb_promotion"


def test_gate_passes_after_a_grant(home):
    core.grant(binding.store(), "subj-1", "kb_promotion", "guardian")
    assert binding.subject_gate("app", "nest_promote", "subj-1") is None


def test_gate_denies_again_after_revoke(home):
    core.grant(binding.store(), "subj-1", "kb_promotion", "guardian")
    core.revoke(binding.store(), "subj-1", "kb_promotion", "guardian")
    assert binding.subject_gate("app", "nest_promote", "subj-1") is not None


def test_gate_exempts_owner_passed_explicitly(home):
    # owner's own data — no grant needed
    assert binding.subject_gate("app", "nest_promote", "me", owner_id="me") is None


def test_gate_exempts_configured_owner(home, monkeypatch):
    monkeypatch.setenv("WILLOW_OWNER_SUBJECT_ID", "the-operator")
    assert binding.subject_gate("app", "nest_promote", "the-operator") is None
    # a different subject still needs a grant
    assert binding.subject_gate("app", "nest_promote", "someone-else") is not None


def test_absent_owner_marker_never_widens_access(home):
    # with no owner configured, even a plausibly-owner id must clear the gate
    assert binding.subject_gate("app", "nest_promote", "operator") is not None


# ── permitted(): read wrapper with owner-exemption ─────────────────────────────

def test_permitted_owner_exempt(home):
    assert binding.permitted("me", "kb_promotion", owner_id="me") is True


def test_permitted_empty_subject_passes(home):
    assert binding.permitted("", "kb_promotion") is True


def test_permitted_non_owner_fail_closed(home):
    assert binding.permitted("subj-1", "kb_promotion") is False
    core.grant(binding.store(), "subj-1", "kb_promotion", "guardian")
    assert binding.permitted("subj-1", "kb_promotion") is True


# ── the operator-only mutation seat ────────────────────────────────────────────

def test_grant_refuses_off_operator_terminal(home):
    # pytest has no interactive operator tty → require_operator_terminal raises
    with pytest.raises(PermissionError):
        binding.grant("subj-1", "kb_promotion", "guardian")


def test_revoke_refuses_off_operator_terminal(home):
    with pytest.raises(PermissionError):
        binding.revoke("subj-1", "kb_promotion", "guardian")


def test_grant_on_operator_terminal_records_chain_receipt_and_disclosure(home, monkeypatch):
    monkeypatch.setattr(binding, "_require_operator_terminal", lambda: None)
    consent = binding.grant("subj-1", "kb_promotion", "guardian")
    assert consent.status == "granted"
    # the grant landed on the core chain
    assert binding.permitted("subj-1", "kb_promotion") is True
    # a receipt was written (subject id hashed, not in the clear)
    assert binding._receipts.records
    _, outcome, status, detail = binding._receipts.records[-1]
    assert outcome == "subject_consent_granted"
    assert "subj-1" not in detail
    assert hashlib.sha256(b"subj-1").hexdigest()[:16] in detail
    # and the subject's own disclosure chain recorded the grant
    discs = core.read_disclosures(binding.store(), "subj-1")
    assert any(d["action"] == "subject_consent_granted" for d in discs)


def test_revoke_on_operator_terminal_flips_the_gate(home, monkeypatch):
    monkeypatch.setattr(binding, "_require_operator_terminal", lambda: None)
    binding.grant("subj-1", "person_inference", "guardian")
    assert binding.permitted("subj-1", "person_inference") is True
    binding.revoke("subj-1", "person_inference", "guardian")
    assert binding.permitted("subj-1", "person_inference") is False


# ── runtime disclosure recording (allowed without an operator terminal) ────────

def test_record_disclosure_runs_at_runtime(home):
    binding.record_disclosure("subj-1", "lesson", "covered fractions")
    discs = core.read_disclosures(binding.store(), "subj-1")
    assert [d["detail"] for d in discs] == ["covered fractions"]
