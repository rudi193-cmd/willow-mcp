"""Operator-signed, per-task network authorization.

The ``# allow_net`` directive is only a request.  Kartikeya calls
``ExecutorNetworkAuthorizer`` immediately before shell execution; this module
then re-checks the host policy and verifies a one-use signed envelope bound to
the submitter and exact normalized task text.

Signing is intentionally not an MCP surface.  ``sign_envelope`` is used only by
the local ``willow-mcp sign-net-task`` command and reads a private key path that
the worker neither needs nor receives.
"""
from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from . import consent, gate, lease

ENVELOPE_FORMAT = "willow-net-auth-v1"
NETWORK_SCOPE = "network"
_NONCE_RE = re.compile(r"^[A-Za-z0-9_-]{22,128}$")
_NET_DIRECTIVES = {"# allow_net", "# allow_localhost"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def normalize_task(task: str) -> str:
    """Normalize transport newlines only; every other byte remains significant."""
    return (task or "").replace("\r\n", "\n").replace("\r", "\n")


def canonical_network_task(task: str) -> str:
    """Produce the exact task representation stored by ``task_submit``."""
    clean = "\n".join(
        line
        for line in normalize_task(task).splitlines()
        if line.strip() not in _NET_DIRECTIVES
    )
    return clean.rstrip("\n") + "\n# allow_net"


def normalized_task_hash(task: str) -> str:
    return hashlib.sha256(normalize_task(task).encode("utf-8")).hexdigest()


def _canonical_payload(payload: dict) -> bytes:
    return json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")


def _parse_deadline(value: object) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _load_private_key(path: str | Path) -> Ed25519PrivateKey:
    raw = Path(path).expanduser().read_bytes()
    key = serialization.load_pem_private_key(raw, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("egress signing key must be an Ed25519 private key")
    return key


def _load_public_key(path: str | Path) -> Ed25519PublicKey:
    raw = Path(path).expanduser().read_bytes()
    key = serialization.load_pem_public_key(raw)
    if not isinstance(key, Ed25519PublicKey):
        raise ValueError("egress verification key must be an Ed25519 public key")
    return key


def sign_envelope(
    *,
    private_key_path: str | Path,
    submitted_by: str,
    task: str,
    ttl_seconds: int,
    nonce: str,
    scope: str = NETWORK_SCOPE,
    now: datetime | None = None,
) -> str:
    """Create a signed envelope. This function is never registered as an MCP tool."""
    if os.environ.get("WILLOW_IN_KART", "").strip():
        raise PermissionError("network authorization cannot be signed inside Kart")
    if not submitted_by.strip():
        raise ValueError("submitted_by is required")
    if scope != NETWORK_SCOPE:
        raise ValueError(f"unsupported network authorization scope {scope!r}")
    if (
        not isinstance(ttl_seconds, int)
        or isinstance(ttl_seconds, bool)
        or ttl_seconds <= 0
        or ttl_seconds > lease.MAX_TTL_SECONDS
    ):
        raise ValueError(
            f"ttl_seconds must be within 1..{lease.MAX_TTL_SECONDS}"
        )
    if not _NONCE_RE.fullmatch(nonce or ""):
        raise ValueError("nonce must be 22..128 URL-safe characters")
    issued = (now or _now()).astimezone(timezone.utc)
    payload = {
        "format": ENVELOPE_FORMAT,
        "submitted_by": submitted_by,
        "task_hash": normalized_task_hash(task),
        "scope": scope,
        "issued_at": issued.isoformat(),
        "expires_at": (issued + timedelta(seconds=ttl_seconds)).isoformat(),
        "nonce": nonce,
    }
    signature = _load_private_key(private_key_path).sign(
        _canonical_payload(payload)
    )
    return json.dumps(
        {
            "payload": payload,
            "signature": base64.b64encode(signature).decode("ascii"),
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def verify_envelope(
    *,
    public_key_path: str | Path,
    submitted_by: str,
    task: str,
    envelope: str,
    now: datetime | None = None,
) -> tuple[bool, str, dict | None]:
    """Verify signature and all task-bound claims without consuming the nonce."""
    try:
        parsed = json.loads(envelope)
    except (TypeError, json.JSONDecodeError):
        return False, "malformed envelope", None
    if not isinstance(parsed, dict):
        return False, "malformed envelope", None
    payload, encoded_sig = parsed.get("payload"), parsed.get("signature")
    if not isinstance(payload, dict) or not isinstance(encoded_sig, str):
        return False, "malformed envelope", None
    if payload.get("format") != ENVELOPE_FORMAT:
        return False, "unsupported envelope format", payload
    if payload.get("submitted_by") != submitted_by:
        return False, "submitted_by mismatch", payload
    if payload.get("scope") != NETWORK_SCOPE:
        return False, "scope mismatch", payload
    if payload.get("task_hash") != normalized_task_hash(task):
        return False, "task hash mismatch", payload
    nonce = payload.get("nonce")
    if not isinstance(nonce, str) or not _NONCE_RE.fullmatch(nonce):
        return False, "malformed nonce", payload
    issued = _parse_deadline(payload.get("issued_at"))
    expires = _parse_deadline(payload.get("expires_at"))
    if issued is None or expires is None:
        return False, "malformed authorization time", payload
    current = (now or _now()).astimezone(timezone.utc)
    if issued > current + timedelta(seconds=30):
        return False, "authorization issued in the future", payload
    if expires <= current:
        return False, "authorization expired", payload
    ttl = (expires - issued).total_seconds()
    if ttl <= 0 or ttl > lease.MAX_TTL_SECONDS:
        return False, "authorization lifetime exceeds policy", payload
    try:
        signature = base64.b64decode(encoded_sig, validate=True)
        public_key = _load_public_key(public_key_path)
        public_key.verify(signature, _canonical_payload(payload))
    except (OSError, TypeError, ValueError, binascii.Error, InvalidSignature):
        return False, "invalid signature", payload
    return True, "verified", payload


def public_key_path() -> Path | None:
    value = os.environ.get("WILLOW_MCP_EGRESS_PUBLIC_KEY", "").strip()
    return Path(value).expanduser() if value else None


def _replay_root() -> Path:
    configured = os.environ.get("WILLOW_MCP_EGRESS_REPLAY_ROOT", "").strip()
    if configured:
        return Path(configured).expanduser()
    store = os.environ.get("WILLOW_STORE_ROOT", "").strip()
    base = Path(store).expanduser() if store else Path.home() / ".willow"
    return base / "egress-replay"


def _consume_nonce(nonce: str) -> bool:
    """Atomically consume one nonce. False means it was already used."""
    root = _replay_root()
    root.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(nonce.encode("ascii")).hexdigest()
    path = root / digest
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(_now().isoformat())
    return True


class ExecutorNetworkAuthorizer:
    """Concrete execution-time policy passed into Kartikeya's host seam."""

    def __init__(self) -> None:
        self.last_error = ""

    def _deny(self, reason: str) -> bool:
        self.last_error = reason
        return False

    def __call__(self, row, envelope: str) -> bool:
        submitted_by = (row.submitted_by or "").strip()
        if not submitted_by:
            return self._deny("submitted_by missing")
        if not gate.permitted(submitted_by, gate.NET_PERMISSION):
            return self._deny("task_net capability denied")
        if not consent.internet_permitted():
            return self._deny("internet consent denied")
        if not lease.active(submitted_by):
            return self._deny("egress lease denied")
        if not lease.strict_trust_root():
            return self._deny("strict trust root is required")
        if lease.self_writable_trust_paths(submitted_by):
            return self._deny("authorization trust root is self-writable")
        public_key = public_key_path()
        if public_key is None:
            return self._deny("verification key is not configured")
        try:
            if not public_key.is_file() or os.access(public_key, os.W_OK):
                return self._deny("verification key is absent or self-writable")
        except OSError:
            return self._deny("verification key is unreadable")
        ok, reason, payload = verify_envelope(
            public_key_path=public_key,
            submitted_by=submitted_by,
            task=row.task,
            envelope=envelope,
        )
        if not ok or payload is None:
            return self._deny(reason)
        try:
            if not _consume_nonce(payload["nonce"]):
                return self._deny("authorization replayed")
        except OSError:
            return self._deny("replay ledger unavailable")
        self.last_error = ""
        return True
