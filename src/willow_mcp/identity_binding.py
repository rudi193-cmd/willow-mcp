"""willow_mcp/identity_binding.py — bind serve-mode OAuth identities to app_id.

Implements docs/design/schema-adaptation.md §6.2-6.3 (SECURITY_AUDIT.md
L-AUTH-02): a Google/Apple sign-in verifies *who* signed in but, on its own,
grants that person no standing under gate.py. A binding maps
(issuer, subject_id) -> app_id. It starts unconfirmed on first sign-in; only
a confirmed binding lets _gate() resolve an authenticated session to real
tool permissions. An authenticated-but-unbound caller is denied, the same as
an unmanifested app_id in stdio mode — fail closed, not fail open.

Confirmation is intentionally NOT exposed as an MCP tool — a remote serve-mode
caller must never be able to confirm their own binding. It is only available
via the local `willow-mcp confirm-binding` CLI subcommand (stdio-only, run by
the operator on the host that owns $WILLOW_HOME).
"""
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


def _write_json_atomic(path: Path, record: dict) -> None:
    """Write via a temp file + atomic rename so a crash mid-write can never
    leave a half-written binding file — which load_binding would then either
    fail to parse (fine, treated as absent) or, worse, parse as valid JSON
    with a truncated/wrong 'confirmed' value."""
    tmp = path.with_suffix(path.suffix + f".tmp-{os.getpid()}")
    tmp.write_text(json.dumps(record, indent=2))
    os.replace(tmp, path)

# Subject/issuer values come from a verified IdP (Google tokeninfo / Apple JWT),
# not raw user input, but they still become filesystem path components here —
# refuse anything that isn't a plain token before touching the filesystem.
_TOKEN_RE = re.compile(r"^[A-Za-z0-9_.\-:]{1,256}$")


def _bindings_root() -> Path:
    home = Path(os.environ.get("WILLOW_HOME", Path.home() / ".willow"))
    root = Path(os.environ.get("WILLOW_MCP_APPS_ROOT", home / "mcp_apps")) / "_identity_bindings"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _safe_token(value: str, label: str) -> str:
    if not value or not _TOKEN_RE.match(value):
        raise ValueError(f"unsafe {label} for binding filename: {value!r}")
    return value


def binding_path(issuer: str, subject_id: str) -> Path:
    issuer = _safe_token(issuer, "issuer")
    subject_id = _safe_token(subject_id, "subject_id")
    return _bindings_root() / f"{issuer}__{subject_id}.json"


def load_binding(issuer: str, subject_id: str) -> Optional[dict]:
    path = binding_path(issuer, subject_id)
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def compute_email_basis(issuer: str, email: Optional[str]) -> str:
    """§6.2: 'do we have an email' is not the interesting question — 'how
    much should anything downstream trust it' is. Google's tokeninfo email
    is IdP-asserted on every sign-in. Apple's may be a one-time snapshot
    (present only on the *first* authorization, silently absent after) or a
    private relay address that silently stops forwarding if the user
    revokes it later — either is a materially weaker guarantee than
    Google's, and code written against Google's always-present email will
    silently misbehave the first time it sees one of these."""
    if not email:
        return "unavailable"
    if issuer == "apple":
        if email.endswith("@privaterelay.appleid.com"):
            return "relay"
        return "first_auth_only"
    return "asserted"


def _note_email_drift(existing: dict, incoming_email: Optional[str]) -> None:
    """§6.3 step 4: if a bound identity's email changes between sign-ins,
    surface it (like §4's schema_drift) rather than silently accepting it.
    Only 'present and different' counts as drift — Apple's email correctly
    disappearing on a later login (subject_id unchanged, see §6.1) must NOT
    be flagged, since that's expected behavior, not an identity change."""
    stored = existing.get("email")
    if not incoming_email or not stored or incoming_email == stored:
        return
    existing["email_drift"] = True
    existing["email_drift_detected_at"] = datetime.now(timezone.utc).isoformat()
    existing["drift_from_email"] = stored
    existing["drift_to_email"] = incoming_email
    _write_json_atomic(binding_path(existing["issuer"], existing["subject_id"]), existing)


def propose_binding(issuer: str, subject_id: str, email: Optional[str]) -> dict:
    """Create an unconfirmed binding artifact on first sign-in.

    Returns the existing record untouched if one is already on disk — a
    repeat sign-in must never silently overwrite a human's prior decision
    (confirmed or not). It may still be annotated in place with an
    email-drift flag (§6.3 step 4) if the incoming email differs from what
    was stored — that's an audit note, not a decision change.
    """
    existing = load_binding(issuer, subject_id)
    if existing is not None:
        _note_email_drift(existing, email)
        return existing
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "issuer": issuer,
        "subject_id": subject_id,
        "email": email,
        "email_basis": compute_email_basis(issuer, email),
        "verified_at": now,
        "app_id": None,
        "confirmed": False,
        "created_at": now,
    }
    _write_json_atomic(binding_path(issuer, subject_id), record)
    return record


def confirm_binding(issuer: str, subject_id: str, app_id: str) -> dict:
    """Operator-only: bind a proposed identity to an app_id and confirm it.

    Not reachable from any MCP tool — call only from the local CLI.
    """
    record = load_binding(issuer, subject_id)
    if record is None:
        raise ValueError(
            f"no proposed binding for ({issuer}, {subject_id}) — "
            "the person must sign in once via the OAuth approval page first"
        )
    record["app_id"] = app_id
    record["confirmed"] = True
    record["confirmed_at"] = datetime.now(timezone.utc).isoformat()
    _write_json_atomic(binding_path(issuer, subject_id), record)
    return record


def resolve_app_id(issuer: str, subject_id: str) -> Optional[str]:
    """Return the bound app_id only if the binding is confirmed — None (fail closed) otherwise."""
    record = load_binding(issuer, subject_id)
    if record and record.get("confirmed") and record.get("app_id"):
        return record["app_id"]
    return None
