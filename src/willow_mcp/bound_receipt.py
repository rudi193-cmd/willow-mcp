"""Canonical bound-receipt schema (#195).

Spec: docs/design/bound-receipt-schema.md
JSON Schema: `willow_mcp/schemas/bound_receipt.v1.schema.json`

This module pins wire shape, ref derivations, and canonical signing bytes.
Writer/verifier crypto and live ref checks are #196; AT-R1 is #194.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Optional

FORMAT_VERSION = "willow-bound-receipt/1"

_DIGEST_RE = re.compile(r"^[a-f0-9]{64}$")
_DENIAL_RE = re.compile(r"^denial:[a-z0-9_]{1,64}$")
_EFFECT_RE = re.compile(r"^effect:[a-f0-9]{64}$")
_SIGNER_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,127}$")
_SIG_ALG = frozenset({"hmac-sha256", "ed25519"})

_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "bound_receipt.v1.schema.json"


class VerificationReason(str, Enum):
    """Distinguishable failure reasons for the staged verify contract."""

    OK = "ok"
    STRUCTURAL_INVALID = "structural_invalid"
    EXPIRED = "expired"
    SIGNATURE_INVALID = "signature_invalid"

    @staticmethod
    def ref_mismatch(field: str) -> str:
        return f"ref_mismatch:{field}"


@dataclass(frozen=True, slots=True)
class BoundReceiptPayload:
    agent_identity_ref: str
    capability_token_ref: str
    policy_or_manifest_digest: str
    tool_call_digest: str
    effect_ref_or_denial_code: str
    ledger_prev: str
    ledger_entry_hash: str
    signer_id: str
    issued_at: str
    expires_at: str

    def to_dict(self) -> dict[str, str]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class BoundReceiptSignature:
    alg: str
    value: str

    def to_dict(self) -> dict[str, str]:
        return {"alg": self.alg, "value": self.value}


@dataclass(frozen=True, slots=True)
class BoundReceiptWire:
    payload: BoundReceiptPayload
    signature: BoundReceiptSignature
    meta: Optional[dict[str, Any]] = None

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "format": FORMAT_VERSION,
            "payload": self.payload.to_dict(),
            "signature": self.signature.to_dict(),
        }
        if self.meta is not None:
            out["meta"] = self.meta
        return out


def schema_path() -> Path:
    return _SCHEMA_PATH


def load_json_schema() -> dict:
    return json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))


# ── Ref derivations (sources documented in bound-receipt-schema.md) ───────────

def agent_identity_ref(agent_id: str, trust_level: int, session_id: str) -> str:
    """Digest of the bound session_bind identity (capped trust + session id)."""
    msg = json.dumps(
        ["session_bind", agent_id, int(trust_level), session_id],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def manifest_acl_digest(manifest: dict) -> str:
    """Capability plane: sorted manifest permission groups / tool names."""
    app_id = manifest.get("app_id")
    perms = sorted({p for p in (manifest.get("permissions") or []) if isinstance(p, str)})
    msg = json.dumps(["manifest-acl", app_id, perms], separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def manifest_policy_digest(manifest: dict) -> str:
    """Policy plane: canonical manifest document bytes (sorted keys at top level)."""
    canonical = json.dumps(manifest, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def tool_call_digest(session_id: str, app_id: str, tool: str, call_nonce: str) -> str:
    """Same message shape as session_binder.call_sig (without the HMAC)."""
    msg = json.dumps(
        ["call", session_id, app_id, tool, call_nonce],
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(msg.encode("utf-8")).hexdigest()


def effect_ref(outcome: str, detail: Optional[str] = None) -> str:
    msg = json.dumps(["effect", outcome, detail], separators=(",", ":"), ensure_ascii=False)
    return f"effect:{hashlib.sha256(msg.encode('utf-8')).hexdigest()}"


def denial_code(code: str) -> str:
    code = re.sub(r"[^a-z0-9_]", "_", code.lower())[:64]
    if not code:
        raise ValueError("denial code must be non-empty")
    return f"denial:{code}"


def ledger_entry_hash(
    prev_hash: str,
    ts: str,
    app_id: str,
    tool: str,
    outcome: str,
    detail: Optional[str],
) -> str:
    """Matches willow_mcp.receipts._entry_hash for cross-linking."""
    payload = json.dumps(
        [prev_hash, ts, app_id, tool, outcome, detail],
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


# ── Canonical signing bytes ───────────────────────────────────────────────────

def canonical_signed_bytes(payload: BoundReceiptPayload | dict[str, str]) -> bytes:
    p = payload if isinstance(payload, dict) else payload.to_dict()
    array = [
        FORMAT_VERSION,
        p["agent_identity_ref"],
        p["capability_token_ref"],
        p["policy_or_manifest_digest"],
        p["tool_call_digest"],
        p["effect_ref_or_denial_code"],
        p["ledger_prev"],
        p["ledger_entry_hash"],
        p["signer_id"],
        p["issued_at"],
        p["expires_at"],
    ]
    return json.dumps(array, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


# ── Structural validation (stage 1) ───────────────────────────────────────────

def _valid_digest(value: Any) -> bool:
    return isinstance(value, str) and bool(_DIGEST_RE.match(value))


def _valid_effect_or_denial(value: Any) -> bool:
    return isinstance(value, str) and (
        bool(_DENIAL_RE.match(value)) or bool(_EFFECT_RE.match(value))
    )


def _parse_timestamp(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(text)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def validate_structure(wire: dict[str, Any]) -> tuple[bool, Optional[VerificationReason], str]:
    """Stage 1: reject malformed receipts before crypto or ref work."""
    if not isinstance(wire, dict):
        return False, VerificationReason.STRUCTURAL_INVALID, "wire must be an object"
    if wire.get("format") != FORMAT_VERSION:
        return False, VerificationReason.STRUCTURAL_INVALID, "bad or missing format"
    if set(wire.keys()) - {"format", "payload", "signature", "meta"}:
        return False, VerificationReason.STRUCTURAL_INVALID, "unknown top-level keys"
    payload = wire.get("payload")
    if not isinstance(payload, dict):
        return False, VerificationReason.STRUCTURAL_INVALID, "payload must be an object"
    expected = set(BoundReceiptPayload.__dataclass_fields__)
    if set(payload.keys()) != expected:
        return False, VerificationReason.STRUCTURAL_INVALID, "payload keys mismatch"
    for key in (
        "agent_identity_ref",
        "capability_token_ref",
        "policy_or_manifest_digest",
        "tool_call_digest",
        "ledger_prev",
        "ledger_entry_hash",
    ):
        if not _valid_digest(payload.get(key)):
            return False, VerificationReason.STRUCTURAL_INVALID, f"bad digest: {key}"
    if not _valid_effect_or_denial(payload.get("effect_ref_or_denial_code")):
        return False, VerificationReason.STRUCTURAL_INVALID, "bad effect_ref_or_denial_code"
    signer = payload.get("signer_id")
    if not isinstance(signer, str) or not _SIGNER_RE.match(signer):
        return False, VerificationReason.STRUCTURAL_INVALID, "bad signer_id"
    for ts_key in ("issued_at", "expires_at"):
        if _parse_timestamp(payload.get(ts_key, "")) is None:
            return False, VerificationReason.STRUCTURAL_INVALID, f"bad timestamp: {ts_key}"
    sig = wire.get("signature")
    if not isinstance(sig, dict) or set(sig.keys()) != {"alg", "value"}:
        return False, VerificationReason.STRUCTURAL_INVALID, "bad signature object"
    if sig.get("alg") not in _SIG_ALG:
        return False, VerificationReason.STRUCTURAL_INVALID, "bad signature alg"
    val = sig.get("value")
    if not isinstance(val, str) or not re.match(r"^[a-f0-9]+$", val):
        return False, VerificationReason.STRUCTURAL_INVALID, "bad signature value"
    if sig["alg"] == "hmac-sha256" and len(val) != 64:
        return False, VerificationReason.STRUCTURAL_INVALID, "hmac-sha256 value must be 64 hex"
    if sig["alg"] == "ed25519" and len(val) != 128:
        return False, VerificationReason.STRUCTURAL_INVALID, "ed25519 value must be 128 hex"
    meta = wire.get("meta")
    if meta is not None and not isinstance(meta, dict):
        return False, VerificationReason.STRUCTURAL_INVALID, "meta must be an object"
    return True, VerificationReason.OK, "ok"


def check_freshness(
    wire: dict[str, Any],
    *,
    now: Optional[datetime] = None,
) -> tuple[bool, VerificationReason, str]:
    """Stage 2: expires_at must be in the future (UTC)."""
    ok, reason, detail = validate_structure(wire)
    if not ok:
        return False, reason, detail  # type: ignore[return-value]
    expires = _parse_timestamp(wire["payload"]["expires_at"])
    assert expires is not None
    now_utc = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    if now_utc > expires:
        return False, VerificationReason.EXPIRED, "expires_at in the past"
    return True, VerificationReason.OK, "ok"


def payload_from_dict(data: dict[str, str]) -> BoundReceiptPayload:
    return BoundReceiptPayload(**data)


def wire_from_dict(data: dict[str, Any]) -> BoundReceiptWire:
    ok, reason, detail = validate_structure(data)
    if not ok:
        raise ValueError(f"{reason}: {detail}")
    return BoundReceiptWire(
        payload=payload_from_dict(data["payload"]),
        signature=BoundReceiptSignature(**data["signature"]),
        meta=data.get("meta"),
    )
