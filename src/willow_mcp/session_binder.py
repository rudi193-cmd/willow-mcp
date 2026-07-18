"""session_binder — cryptographic agent identity binding (willow-gate seam, H1).

The agent-side counterpart to `identity_binding` (which binds serve-mode OAuth
*humans*): agents don't OAuth, so their app_id is otherwise just a string. This
binds it. Two verbs, exactly the H1 spike promoted to real code:

  * check_in(header): HMAC-verify a 13-field header against the agent's registered
    secret, cap the claimed trust at the registered ceiling, refuse a replayed
    nonce → a live bound session.
  * verify_call(session_id, app_id, tool, call_nonce, sig): the SIGNED per-call
    check — a call carries a fresh nonce and an HMAC over
    (session_id|app_id|tool|call_nonce). Recompute, reject a reused nonce, and
    require the session's agent_id == the call's app_id. This is what stops the
    "pass app_id=operator and ride the live session" hole: a bearer session token
    would not, a per-call signature does (see the H1 spike).

Phase 2 is OBSERVE-ONLY: `_gate` calls this to LOG the binding, never to change a
decision. Pure stdlib (hmac/hashlib) — no willow-gate dependency, no PGP.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Optional

from . import agent_registry, paths

# (name, read_only) — the ladder for logging; D1 maps tiers→groups at enforcement.
TRUST_LEVELS = {
    0: ("Exiled", True), 1: ("Rookie", True), 2: ("Steady", False),
    3: ("Veteran", False), 4: ("Elder", False),
}
REQUIRED_FIELDS = {
    "agent_id", "agent_name", "last_gate", "pass_count", "fail_count", "drift",
    "nonce", "trust_level", "timestamp", "tools", "state_hash", "signature",
    "reserved",
}
_SIGNED_FIELDS = sorted(REQUIRED_FIELDS - {"signature"})


class BindError(Exception):
    """A check-in / verification refusal. Carries a short machine reason."""


def _canonical(header: dict) -> bytes:
    return json.dumps({k: header[k] for k in _SIGNED_FIELDS},
                      sort_keys=True, separators=(",", ":")).encode()


def expected_header_sig(secret: bytes, header: dict) -> str:
    return hmac.new(secret, _canonical(header), hashlib.sha256).hexdigest()


def call_sig(secret: bytes, session_id: str, app_id: str, tool: str, call_nonce: str) -> str:
    msg = f"{session_id}|{app_id}|{tool}|{call_nonce}".encode()
    return hmac.new(secret, msg, hashlib.sha256).hexdigest()


class SessionBinder:
    def __init__(self):
        self._sessions: dict = {}          # nonce -> session dict (process-lived)
        self._used_nonces_file = paths.willow_home() / "gate" / "used_checkin_nonces"

    # ── check-in ──────────────────────────────────────────────────────────────
    def _load_used(self) -> set:
        try:
            return set((self._used_nonces_file.read_text()).split())
        except OSError:
            return set()

    def _mark_used(self, nonce: str) -> None:
        self._used_nonces_file.parent.mkdir(parents=True, exist_ok=True)
        with self._used_nonces_file.open("a") as f:
            f.write(nonce + "\n")

    def check_in(self, header: dict) -> dict:
        """Verify a header and open a bound session. Raises BindError on any
        refusal (fail-closed). Returns the session (nonce is its id)."""
        if not isinstance(header, dict):
            raise BindError("header must be an object")
        missing = REQUIRED_FIELDS - set(header)
        if missing:
            raise BindError(f"missing fields: {sorted(missing)}")
        if set(header) - REQUIRED_FIELDS:
            raise BindError("unknown fields present")          # 13 in, 13 out
        if header["reserved"] != 0:
            raise BindError("trap field 'reserved' must be 0")
        trust = header["trust_level"]
        if trust not in TRUST_LEVELS:
            raise BindError(f"bad trust_level: {trust}")
        if len(str(header["nonce"])) != 32:
            raise BindError("nonce must be 32 chars")
        if len(str(header["signature"])) != 64:
            raise BindError("signature must be 64 hex chars")

        agent_id = header["agent_id"]
        loaded = agent_registry.load(agent_id)
        if loaded is None:
            raise BindError(f"unregistered agent_id: {agent_id!r}")
        secret, ceiling = loaded
        if not hmac.compare_digest(expected_header_sig(secret, header), str(header["signature"])):
            raise BindError("signature mismatch — identity not verified")
        if int(trust) > int(ceiling):
            raise BindError(f"trust claim {trust} exceeds registered ceiling {ceiling}")

        nonce = str(header["nonce"])
        if nonce in self._load_used() or nonce in self._sessions:
            raise BindError("nonce already used — replay refused")
        self._mark_used(nonce)

        name, read_only = TRUST_LEVELS[int(trust)]
        session = {"session_id": nonce, "agent_id": agent_id, "trust_level": int(trust),
                   "tier": name, "read_only": read_only, "used_call_nonces": set()}
        self._sessions[nonce] = session
        return {k: session[k] for k in ("session_id", "agent_id", "trust_level", "tier", "read_only")}

    # ── per-call verification (SIGNED; H1) ─────────────────────────────────────
    def verify_call(self, session_id: str, app_id: str, tool: str,
                    call_nonce: str, sig: str) -> dict:
        """Verify a per-call credential binds this call to a live check-in.
        Returns {bound, agent_id, trust_level, tier, reason}. bound=False with a
        reason on any failure — never raises (the caller only observes)."""
        sess = self._sessions.get(session_id or "")
        if sess is None:
            return {"bound": False, "reason": "no live session for session_id"}
        if not call_nonce or call_nonce in sess["used_call_nonces"]:
            return {"bound": False, "reason": "missing or replayed call_nonce"}
        loaded = agent_registry.load(sess["agent_id"])
        if loaded is None:
            return {"bound": False, "reason": "agent no longer registered"}
        secret, _ = loaded
        if not hmac.compare_digest(call_sig(secret, session_id, app_id, tool, call_nonce), sig or ""):
            return {"bound": False, "reason": "call signature mismatch"}
        if sess["agent_id"] != app_id:
            return {"bound": False, "reason": "signed session is not this app_id"}
        sess["used_call_nonces"].add(call_nonce)
        return {"bound": True, "agent_id": sess["agent_id"], "trust_level": sess["trust_level"],
                "tier": sess["tier"], "read_only": sess["read_only"], "reason": "verified"}

    def session_for(self, app_id: str) -> Optional[dict]:
        """The most recent live session bound to this app_id, if any (used by the
        observe hook when no per-call credential was presented)."""
        for s in reversed(list(self._sessions.values())):
            if s["agent_id"] == app_id:
                return s
        return None
