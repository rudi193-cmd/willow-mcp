"""Bound receipt schema (#195) — canonical bytes, structure, JSON Schema alignment."""
from __future__ import annotations

import copy
from datetime import datetime, timezone

import jsonschema
import pytest

from willow_mcp import bound_receipt as br
from willow_mcp.receipts import ReceiptLog


def _sample_payload(**overrides) -> dict:
    manifest = {"app_id": "kart", "permissions": ["store_read", "task_submit"]}
    base = {
        "agent_identity_ref": br.agent_identity_ref("kart", 2, "a" * 32),
        "capability_token_ref": br.manifest_acl_digest(manifest),
        "policy_or_manifest_digest": br.manifest_policy_digest(manifest),
        "tool_call_digest": br.tool_call_digest("a" * 32, "kart", "store_get", "n1"),
        "effect_ref_or_denial_code": br.effect_ref("ok", None),
        "ledger_prev": "0" * 64,
        "ledger_entry_hash": br.ledger_entry_hash(
            "0" * 64,
            "2026-07-31T21:00:00+00:00",
            "kart",
            "store_get",
            "ok",
            None,
        ),
        "signer_id": "willow-operator",
        "issued_at": "2026-07-31T21:00:00+00:00",
        "expires_at": "2099-01-01T00:00:00+00:00",
    }
    base.update(overrides)
    return base


def _sample_wire(**payload_overrides) -> dict:
    return {
        "format": br.FORMAT_VERSION,
        "payload": _sample_payload(**payload_overrides),
        "signature": {"alg": "hmac-sha256", "value": "a" * 64},
        "meta": {"note": "unsigned"},
    }


def test_canonical_signed_bytes_is_deterministic():
    p = _sample_payload()
    b1 = br.canonical_signed_bytes(p)
    b2 = br.canonical_signed_bytes(p)
    assert b1 == b2
    p2 = copy.deepcopy(p)
    p2["agent_identity_ref"] = "b" * 64
    assert br.canonical_signed_bytes(p2) != b1


def test_meta_is_outside_signed_envelope():
    wire = _sample_wire()
    bytes_a = br.canonical_signed_bytes(wire["payload"])
    wire["meta"]["tamper"] = True
    assert br.canonical_signed_bytes(wire["payload"]) == bytes_a


def test_validate_structure_accepts_sample():
    ok, reason, _ = br.validate_structure(_sample_wire())
    assert ok and reason == br.VerificationReason.OK


def test_json_schema_accepts_sample():
    schema = br.load_json_schema()
    jsonschema.validate(_sample_wire(), schema)


@pytest.mark.parametrize(
    "mutator",
    [
        lambda w: w.pop("format"),
        lambda w: w.update({"format": "other"}),
        lambda w: w["payload"].pop("ledger_prev"),
        lambda w: w["payload"].update({"ledger_prev": "not-hex"}),
        lambda w: w["payload"].update({"effect_ref_or_denial_code": "nope"}),
        lambda w: w["signature"].update({"value": "zz"}),
    ],
)
def test_validate_structure_rejects_bad_wire(mutator):
    wire = _sample_wire()
    mutator(wire)
    ok, reason, detail = br.validate_structure(wire)
    assert not ok
    assert reason == br.VerificationReason.STRUCTURAL_INVALID


def test_check_freshness_expired():
    wire = _sample_wire(expires_at="2020-01-01T00:00:00+00:00")
    ok, reason, _ = br.check_freshness(
        wire, now=datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert not ok and reason == br.VerificationReason.EXPIRED


def test_ledger_entry_hash_matches_receipt_log(tmp_path):
    log = ReceiptLog(db_path=str(tmp_path / "r.db"))
    log.record("kart", "store_get", "ok")
    rows = log.verify()
    assert rows["ok"]
    # Internal consistency: recompute head from stored row via public helper.
    import sqlite3

    con = sqlite3.connect(str(tmp_path / "r.db"))
    row = con.execute(
        "SELECT ts, app_id, tool, outcome, detail, prev_hash FROM receipts ORDER BY id DESC LIMIT 1"
    ).fetchone()
    con.close()
    ts, app_id, tool, outcome, detail, prev = row
    assert br.ledger_entry_hash(prev, ts, app_id, tool, outcome, detail) == rows["head"]


def test_ref_helpers_stable():
    m = {"app_id": "x", "permissions": ["b", "a"]}
    assert br.manifest_acl_digest(m) == br.manifest_acl_digest(m)
    assert br.manifest_policy_digest(m) == br.manifest_policy_digest(m)
    assert br.tool_call_digest("s", "x", "t", "c") != br.tool_call_digest("s", "x", "t", "d")
