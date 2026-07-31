"""AT-R1 (#194) — bound receipt integrity: one ref mutation ⇒ distinguishable failure."""
from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone

import pytest

from willow_mcp import bound_receipt as br

_OPERATOR_KEY = b"willow-operator-mac-test"
_SIGNER = "willow-operator"


def _sources(**overrides) -> br.ReceiptSources:
    manifest = {"app_id": "kart", "permissions": ["store_read", "task_submit"]}
    base = br.ReceiptSources(
        agent_id="kart",
        trust_level=2,
        session_id="c" * 32,
        manifest=manifest,
        app_id="kart",
        tool="store_get",
        call_nonce="nonce-1",
        ledger_prev="0" * 64,
        ledger_ts="2026-07-31T22:00:00+00:00",
        ledger_app_id="kart",
        ledger_tool="store_get",
        ledger_outcome="ok",
        ledger_detail=None,
        effect_outcome="ok",
    )
    if overrides:
        return replace(base, **overrides)
    return base


def _valid_wire(**write_kw) -> dict:
    return br.write_receipt(
        sources=_sources(),
        signing_key=_OPERATOR_KEY,
        signer_id=_SIGNER,
        ttl_seconds=3600,
        issued_at=datetime(2026, 7, 31, 22, 0, tzinfo=timezone.utc),
        **write_kw,
    )


def test_valid_receipt_verifies():
    wire = _valid_wire()
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
    )
    assert result.ok and result.reason == br.VerificationReason.OK.value


@pytest.mark.parametrize("field", br._PAYLOAD_REF_FIELDS)
def test_mutated_ref_fails_with_ref_mismatch(field):
    wire = _valid_wire()
    if field == "effect_ref_or_denial_code":
        wire["payload"][field] = br.denial_code("tampered")
    else:
        wire["payload"][field] = "f" * 64
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
    )
    assert not result.ok
    assert result.reason == br.VerificationReason.ref_mismatch(field)


def test_ledger_prev_link_break_fails():
    wire = _valid_wire()
    wire["payload"]["ledger_prev"] = "a" * 64
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
    )
    assert result.reason == br.VerificationReason.ref_mismatch("ledger_prev")


def test_ledger_entry_hash_break_fails():
    wire = _valid_wire()
    wire["payload"]["ledger_entry_hash"] = "b" * 64
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
    )
    assert result.reason == br.VerificationReason.ref_mismatch("ledger_entry_hash")


def test_tampered_signature_fails():
    wire = _valid_wire()
    wire["signature"]["value"] = "0" * 64
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2026, 7, 31, 22, 1, tzinfo=timezone.utc),
    )
    assert result.reason == br.VerificationReason.SIGNATURE_INVALID.value


def test_expired_fails_before_refs_or_signature():
    wire = _valid_wire()
    result = br.verify_receipt(
        wire,
        signing_key=_OPERATOR_KEY,
        sources=_sources(),
        now=datetime(2099, 1, 2, tzinfo=timezone.utc),
    )
    assert result.reason == br.VerificationReason.EXPIRED.value


def test_write_refuses_without_key():
    with pytest.raises(br.BoundReceiptError):
        br.write_receipt(sources=_sources(), signing_key=b"", signer_id=_SIGNER)


def test_table_row_per_ref_visible_in_parametrize():
    """Guard: new payload ref ⇒ add a AT-R1 parametrize row (field list is shared)."""
    assert len(br._PAYLOAD_REF_FIELDS) == 7
