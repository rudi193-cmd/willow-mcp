"""subject_consent.core — consent for a subject who isn't the owner.

The stdlib-only, egress-free heart of the guardian-consent seam
(docs/design/guardian-consent-seam.md). It answers a question no other
authorization surface in the stack can: *did this person — or a guardian on
their behalf — agree to their data being used this way?*

This is the convergence of a gap that was designed twice and built zero times:
corpus-lens named `owner != subject` its "biggest unshipped gap" and refused to
ship it; the willow-mcp seam doc mapped it; UTETY built a private copy for a
child learner. This module is the one shared primitive all three can depend on.

HARD CONSTRAINT — stdlib only, no network, no FFI, no willow-mcp runtime deps.
UTETY runs this on a child's device; corpus-lens is stdlib-only by charter. So
this file imports nothing but the standard library, and `tests/` enforces it.
The willow-mcp binding (gate wiring, ReceiptLog) lives in a separate module that
may import the engine; this core must not drag it in behind it.

Everything here is FAIL-CLOSED, exactly like willow_mcp.consent: absence,
unparseability, a broken chain, `pending`, or `revoked` all resolve to denied.
Mutation (`grant`/`revoke`) is a library primitive an *operator CLI* calls — an
app can never grant consent on a subject's behalf; enforcing that is the
binding's job, not this core's.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# ── vocabulary ────────────────────────────────────────────────────────────────

#: What a subject can consent to. INDEPENDENT permissions, deliberately NOT a
#: ladder: a person-inference that stays local is not "more" than a de-identified
#: KB promotion — they are different uses, so each is granted (and checked)
#: on its own. `person_inference` is the same name as corpus-lens's capability.
SCOPES: tuple[str, ...] = (
    "local_only",        # the subject's data may live on this device
    "process_analysis",  # process/structure may be derived (corpus-lens, Nest counts)
    "kb_promotion",      # de-identified structure may cross into the shared KB
    "person_inference",  # a person-shaped claim about the subject may be made at all
)

#: How a subject relates to the owner. `self` means owner == subject (the
#: binding may exempt that case; the core does not — it only records grants).
RELATIONS: tuple[str, ...] = ("self", "child", "ward", "household", "other")

# UTETY's exact lifecycle. Anything that is not GRANTED is denied.
PENDING = "pending"
GRANTED = "granted"
REVOKED = "revoked"
_STATUSES = frozenset({PENDING, GRANTED, REVOKED})

_GENESIS = ""  # prev_hash of the first row in a chain


class SubjectConsentError(Exception):
    """Base for this module."""


class DeidentificationError(SubjectConsentError):
    """A boundary crossing could not prove its scrub. Never carries the value."""


class ChainTamperError(SubjectConsentError):
    """A hash chain failed verification (mid-chain edit or tail truncation)."""


# ── records ───────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Subject:
    """A person the data is about. `id` is opaque and local — never a name on
    the wire. `can_self_consent` is carried but its *policy* (age/capacity) is
    deferred to the binding; the core does not judge it."""
    id: str
    relation_to_owner: str = "other"
    can_self_consent: bool = False


@dataclass(frozen=True)
class Consent:
    """One transition in a subject's consent chain. Tamper-evident: `hash`
    covers the canonical payload AND `prev_hash`, so any edit or truncation
    breaks the links."""
    subject_id: str
    scope: str
    status: str
    granted_by: str
    at: str            # ISO-8601 UTC
    prev_hash: str
    hash: str

    def payload(self) -> dict:
        """The signed portion — everything but `hash`."""
        return {
            "subject_id": self.subject_id,
            "scope": self.scope,
            "status": self.status,
            "granted_by": self.granted_by,
            "at": self.at,
            "prev_hash": self.prev_hash,
        }


# ── hashing (shared by the consent chain and the disclosure chain) ─────────────

def _canonical(payload: dict) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")


def _row_hash(payload: dict) -> str:
    return hashlib.sha256(_canonical(payload)).hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── store layout ───────────────────────────────────────────────────────────────
# A store is a directory:
#   <store>/consent.jsonl                 — the consent transition chain
#   <store>/disclosures/<subject_id>.jsonl — per-subject disclosure chain
# Both are append-only, hash-chained JSONL. Nothing is ever rewritten in place;
# revocation adds a row, never removes one (erasing *when* consent was withdrawn
# would gut the audit trail — UTETY audit B2).

def _consent_path(store: Path) -> Path:
    return store / "consent.jsonl"


def _disclosure_path(store: Path, subject_id: str) -> Path:
    # subject_id is opaque; hash it for the filename so an id can never escape
    # the directory or leak a name onto the filesystem.
    safe = hashlib.sha256(subject_id.encode("utf-8")).hexdigest()[:32]
    return store / "disclosures" / f"{safe}.jsonl"


def _read_chain(path: Path) -> list[dict] | None:
    """Return the raw rows, or None if the file is absent/unreadable. Never
    raises — a caller in the deny path must not be handed an exception."""
    if not path.is_file():
        return None
    rows: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            obj = json.loads(line)
            if not isinstance(obj, dict):
                return None
            rows.append(obj)
    except Exception:
        return None
    return rows


def _chain_ok(rows: list[dict]) -> bool:
    """Verify the hash links end to end. A break anywhere ⇒ not ok."""
    prev = _GENESIS
    for row in rows:
        h = row.get("hash")
        payload = {k: row.get(k) for k in row if k != "hash"}
        if payload.get("prev_hash") != prev:
            return False
        if not isinstance(h, str) or _row_hash(payload) != h:
            return False
        prev = h
    return True


def _append(path: Path, payload: dict) -> str:
    """Append one hash-chained row, linking to the current tail. Returns the new
    head hash. Verifies the existing chain first and REFUSES to extend a broken
    one (a tampered store must not be silently continued)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    existing = _read_chain(path) or []
    if existing and not _chain_ok(existing):
        raise ChainTamperError("refusing to append to a broken chain")
    prev = existing[-1]["hash"] if existing else _GENESIS
    payload = dict(payload, prev_hash=prev)
    h = _row_hash(payload)
    row = dict(payload, hash=h)
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, sort_keys=True) + "\n")
    return h


# ── consent: mutation (operator/CLI primitives — never an MCP tool) ────────────

def grant(store: Path, subject_id: str, scope: str, granted_by: str) -> Consent:
    """Record a GRANTED transition. Raises on an unknown scope or empty grantor
    (a grant with no author is not a grant)."""
    return _transition(store, subject_id, scope, GRANTED, granted_by)


def revoke(store: Path, subject_id: str, scope: str, revoked_by: str) -> Consent:
    """Record a REVOKED transition. Denies from this moment on, permanently on
    the record."""
    return _transition(store, subject_id, scope, REVOKED, revoked_by)


def _transition(store: Path, subject_id: str, scope: str, status: str, by: str) -> Consent:
    if scope not in SCOPES:
        raise SubjectConsentError(f"unknown scope: {scope!r}")
    if status not in _STATUSES:
        raise SubjectConsentError(f"unknown status: {status!r}")
    if not (subject_id and subject_id.strip()):
        raise SubjectConsentError("subject_id required")
    if not (by and by.strip()):
        raise SubjectConsentError("granted_by/revoked_by required")
    payload = {
        "subject_id": subject_id,
        "scope": scope,
        "status": status,
        "granted_by": by,
        "at": _now(),
    }
    h = _append(_consent_path(store), payload)
    return Consent(hash=h, prev_hash="", **payload)  # prev_hash set inside _append; returned value is informational


# ── consent: the gate (read-only, fail-closed — mirrors consent.permitted) ─────

def permitted(store: Path, subject_id: str, scope: str) -> bool:
    """True only when the latest transition for (subject_id, scope) is a
    verified GRANTED. Fail-closed on every other path:

      - store/file absent            → False
      - unparseable or broken chain  → False
      - no record for this pair      → False
      - latest is pending or revoked → False

    Unknown scope is a programming error, denied loudly-in-log but still False.
    Owner == subject is NOT special-cased here; that exemption (if any) belongs
    to the binding that knows who the owner is. This core only knows grants.
    """
    if scope not in SCOPES:
        return False
    rows = _read_chain(_consent_path(store))
    if not rows or not _chain_ok(rows):
        return False
    latest: dict | None = None
    for row in rows:
        if row.get("subject_id") == subject_id and row.get("scope") == scope:
            latest = row
    return bool(latest) and latest.get("status") == GRANTED


def verify_consent_chain(store: Path) -> None:
    """Admin/diagnostic path: raise ChainTamperError if the consent chain is
    broken (the gate silently denies; this one tells you *why*)."""
    rows = _read_chain(_consent_path(store))
    if rows is None:
        return  # absent is not tampered
    if not _chain_ok(rows):
        raise ChainTamperError("consent chain failed verification")


# ── the de-identify-or-refuse boundary (from UTETY's knowledge.py) ─────────────

def deidentify(text: str, identifiers: list[str]) -> str:
    """Remove each identifier from `text`, then PROVE the scrub or raise.

    The only thing that may cross a sharing boundary about a subject is a
    de-identified derivative, and the scrub is verified or it refuses. If any
    identifier survives (case-insensitive), this raises DeidentificationError —
    and the error NEVER contains the surviving value or the text, exactly like
    UTETY's `deidentify()`. `identified is person; de-identified is process`.
    """
    if not isinstance(text, str):
        raise DeidentificationError("de-identification input was not text")
    out = text
    for ident in identifiers:
        if not ident:
            continue
        # case-insensitive removal without echoing the identifier anywhere
        low = out.lower()
        needle = ident.lower()
        idx = low.find(needle)
        while idx != -1:
            out = out[:idx] + "█" * len(ident) + out[idx + len(ident):]
            low = out.lower()
            idx = low.find(needle)
    # verify: no identifier may survive
    low = out.lower()
    for ident in identifiers:
        if ident and ident.lower() in low:
            raise DeidentificationError(
                "de-identification failed to clean the text"  # value withheld on purpose
            )
    return out


# ── the disclosure chain (per subject — the guardian's readable record) ────────

def record_disclosure(store: Path, subject_id: str, action: str, detail: str = "") -> str:
    """Append a hash-chained disclosure row: what was done with this subject's
    data. This is the record a guardian can read ("what the tutor discussed with
    your child"). Returns the new head hash."""
    if not (subject_id and subject_id.strip()):
        raise SubjectConsentError("subject_id required")
    payload = {
        "subject_id": subject_id,
        "action": action,
        "detail": detail,
        "at": _now(),
    }
    return _append(_disclosure_path(store, subject_id), payload)


def read_disclosures(store: Path, subject_id: str) -> list[dict]:
    """Return the verified disclosure chain for a subject. Raises
    ChainTamperError if the chain is broken — a guardian's record that cannot
    prove its own integrity must announce that, not quietly return rows."""
    rows = _read_chain(_disclosure_path(store, subject_id))
    if rows is None:
        return []
    if not _chain_ok(rows):
        raise ChainTamperError("disclosure chain failed verification")
    return rows
