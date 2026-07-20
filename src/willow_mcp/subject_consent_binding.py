"""The willow-mcp binding for the guardian-consent core.

`subject_consent.core` is deliberately blind: stdlib-only, egress-free, and it
does not know who the owner is, who is allowed to grant, or how willow-mcp
audits. Those three facts are exactly what this binding supplies — and why it
lives here, outside the stdlib-only package, free to import the willow-mcp
runtime the core must never drag in behind it.

Three jobs, each one the core left to "the binding":

1. **Owner-exemption.** The core does not special-case owner == subject; it only
   records grants. The binding *does* know the owner, so it answers the one
   question the core can't: a subject who is the operator themselves needs no
   grant — the owner consents to their own data by operating the machine. Any
   *other* subject falls through to the core's fail-closed gate.

2. **The gate, composed by AND.** `gate.permitted` already asked *may this app
   call this tool?* (capability consent). This adds the orthogonal third check —
   *did this non-owner subject agree to this scope?* (subject consent) — the same
   shape as the three-key egress gate: more keys, never fewer. A tool that does
   not touch a subject is unaffected; a call that carries a non-owner `subject_id`
   must clear the core gate or it is denied and receipted `subject_consent_denied`.

3. **The operator-only mutation seat.** `grant`/`revoke` here are NOT MCP tools.
   They demand a real operator terminal (like `consent_admin`), so an app can
   never grant consent on a subject's behalf — granting is an owner-side act, like
   minting a manifest. Every grant/revoke is also written to the willow-mcp
   ReceiptLog *and* the subject's own disclosure chain, so the act is loud on both
   the system audit and the guardian-readable record.
"""
from __future__ import annotations

import logging
import os

from . import paths
from .receipts import ReceiptLog
from .subject_consent import core

logger = logging.getLogger("willow_mcp.subject_consent_binding")

# One shared receipt log with the server would be ideal, but the mutation seat
# runs from the operator CLI (no server process), so the binding owns its own —
# it points at the same WILLOW_MCP_RECEIPT_DB, so the lines land in one place.
_receipts = ReceiptLog()


def store():
    """The consent store directory the core reads and writes."""
    return paths.subject_consent_store()


# ── who is the owner ───────────────────────────────────────────────────────────
# The binding knows the owner; the core does not. If the operator names their own
# subject_id, a call about the owner's own data is exempt from subject consent
# (they consent by operating). Unset ⇒ no subject is the owner ⇒ every subject_id
# needs a grant — stricter, and the safe default: an *absent* owner marker must
# never widen access, only ever narrow it.

def owner_subject_id() -> str:
    return os.environ.get("WILLOW_OWNER_SUBJECT_ID", "").strip()


def _is_owner(subject_id: str) -> bool:
    owner = owner_subject_id()
    return bool(owner) and subject_id == owner


# ── which tools touch a subject, and at what scope ─────────────────────────────
# The seam-doc mechanism: a tool declares whether it touches a subject and at
# what scope (like tier_policy.TOOL_CLASS). A tool absent from this map is not
# subject-scoped — the gate is a no-op for it. Only tools whose whole purpose is
# to move a subject's data across a boundary appear here. Kept minimal on purpose:
# a scope is a promise to enforce, so an entry is added only when the call site
# can actually supply a `subject_id`. (Wiring `_gate` to pass one through is the
# next slice; until then this map is correct-but-dormant, never wrong.)
TOOL_SUBJECT_SCOPE: dict[str, str] = {
    # de-identified structure crossing into the shared KB
    "nest_promote": "kb_promotion",
    "kb_ingest": "kb_promotion",
    "knowledge_ingest": "kb_promotion",
    # a person-shaped claim being made at all (corpus-lens's quarantined bar)
    "lineage_record": "person_inference",
}


def required_scope(tool_name: str) -> str | None:
    """The subject-consent scope a tool requires, or None if it touches no
    subject. Fail-closed only where a scope is declared: an unlisted tool is
    genuinely not subject-scoped, not a policy hole."""
    return TOOL_SUBJECT_SCOPE.get(tool_name)


# ── the read gate (runtime, fail-closed) ───────────────────────────────────────

def permitted(subject_id: str, scope: str, *, owner_id: str | None = None) -> bool:
    """Fail-closed subject-consent check with owner-exemption applied.

    Owner (owner_id, or the configured owner_subject_id) is exempt — their own
    data needs no grant. Every other subject defers to the core, which denies on
    every path that is not a verified GRANTED. An empty subject_id means "no
    subject in play" and passes; enforcing *that* a subject_id is present when a
    scope is required is the gate's job, below."""
    if not (subject_id and subject_id.strip()):
        return True
    if owner_id and subject_id == owner_id:
        return True
    if _is_owner(subject_id):
        return True
    return core.permitted(store(), subject_id, scope)


def subject_gate(
    app_id: str,
    tool_name: str,
    subject_id: str | None,
    *,
    owner_id: str | None = None,
) -> dict | None:
    """The third gate check, composed after `gate.permitted` by AND.

    Returns None to allow, or an error dict (shaped like `_gate`'s) to deny. A
    tool that touches no subject, or a call about the owner's own data, allows.
    A call carrying a non-owner subject_id must clear the core's fail-closed gate.
    """
    scope = required_scope(tool_name)
    if scope is None:
        return None  # tool is not subject-scoped
    if not (subject_id and subject_id.strip()):
        return None  # no subject named ⇒ nothing to consent for on this call
    if owner_id and subject_id == owner_id:
        return None
    if _is_owner(subject_id):
        return None
    if core.permitted(store(), subject_id, scope):
        return None
    return {
        "error": (
            f"subject_consent_denied: '{tool_name}' touches a non-owner subject "
            f"at scope '{scope}', and no verified consent grant exists for it. "
            f"An operator must run `willow-mcp grant-consent <subject> {scope} "
            f"--by <guardian>` before this call can proceed."
        ),
        "code": "subject_consent_denied",
        "scope": scope,
    }


# ── the operator-only mutation seat (NOT an MCP tool) ──────────────────────────

def _require_operator_terminal() -> None:
    # Same non-forgeable boundary consent_admin uses: not in Kart, a real
    # operator-owned controlling terminal. Granting consent for a subject is an
    # owner-side act; an app calling this path must be refused before it writes.
    from .human_session import require_operator_terminal

    require_operator_terminal()


def grant(subject_id: str, scope: str, granted_by: str) -> core.Consent:
    """Operator-CLI primitive: record a GRANTED transition, receipt it, and log
    it on the subject's own disclosure chain. Refuses off an operator terminal."""
    _require_operator_terminal()
    consent = core.grant(store(), subject_id, scope, granted_by)
    _after_mutation("subject_consent_granted", subject_id, scope, granted_by)
    return consent


def revoke(subject_id: str, scope: str, revoked_by: str) -> core.Consent:
    """Operator-CLI primitive: record a REVOKED transition, receipt it, and log
    it on the subject's own disclosure chain. Refuses off an operator terminal."""
    _require_operator_terminal()
    consent = core.revoke(store(), subject_id, scope, revoked_by)
    _after_mutation("subject_consent_revoked", subject_id, scope, revoked_by)
    return consent


def _after_mutation(outcome: str, subject_id: str, scope: str, by: str) -> None:
    # subject_id is opaque; the receipt names the scope and hashes the id so the
    # system audit never carries a subject's identifier in the clear.
    import hashlib

    sid = hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:16]
    try:
        _receipts.record("operator", outcome, "ok", f"subject={sid} scope={scope} by={by}")
    except Exception:  # audit is best-effort; the grant already landed on the chain
        logger.warning("subject_consent: receipt write failed for %s", outcome)
    try:
        core.record_disclosure(store(), subject_id, outcome, f"scope={scope} by={by}")
    except Exception:
        logger.warning("subject_consent: disclosure write failed for %s", outcome)


# ── runtime disclosure recording (not a mutation — safe to call from a tool) ───

def record_disclosure(subject_id: str, action: str, detail: str = "") -> str:
    """Append to a subject's disclosure chain what was done with their data, and
    mirror a line to the system audit. Recording a disclosure is not granting
    consent, so this — unlike grant/revoke — may run at runtime."""
    head = core.record_disclosure(store(), subject_id, action, detail)
    import hashlib

    sid = hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:16]
    try:
        _receipts.record("operator", "subject_disclosure", "ok", f"subject={sid} action={action}")
    except Exception:
        logger.warning("subject_consent: disclosure receipt failed")
    return head
