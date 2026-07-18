"""Fail-closed constitutional envelope matching and citation-before-act."""
from __future__ import annotations

import fnmatch
import json
import os
from datetime import datetime, timezone
from pathlib import Path

from .governance_ledger import GovernanceLedger
from .paths import trusted_read


def registry_path() -> Path:
    configured = os.environ.get("WILLOW_ENVELOPE_REGISTRY", "").strip()
    if configured:
        return Path(configured).expanduser()
    project = os.environ.get("WILLOW_PROJECT_ROOT", "").strip()
    root = Path(project).expanduser() if project else Path.home() / "github" / "willow"
    return root / "envelopes" / "pre-approved.json"


def syscall_path() -> Path:
    configured = os.environ.get("WILLOW_SYSCALL_TABLE", "").strip()
    if configured:
        return Path(configured).expanduser()
    return registry_path().with_name("syscall-table.json")


def _load(path: Path) -> dict:
    # Authenticate the input's trust root before believing its bytes (§4.6): a
    # writable/symlinked registry or syscall table is a forged-envelope vector.
    trusted_read(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"{path.name} must contain an object")
    return data


def _deadline(value) -> datetime | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("expires_at must be a timestamp/date or null")
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _granted(grantee, actor: str) -> bool:
    return actor == grantee or (
        isinstance(grantee, list) and actor in grantee
    )


def _bound_matches(grant, actual) -> bool:
    if isinstance(grant, list):
        if isinstance(actual, list):
            return all(
                any(fnmatch.fnmatch(str(item), str(pattern)) for pattern in grant)
                for item in actual
            )
        return any(
            fnmatch.fnmatch(str(actual), str(pattern)) for pattern in grant
        )
    return actual == grant


class EnvelopeAuthority:
    def __init__(self, ledger: GovernanceLedger):
        self.ledger = ledger

    def _registry(self) -> tuple[dict, dict[int, dict]]:
        registry = _load(registry_path())
        table = _load(syscall_path())
        verbs = {
            int(row["id"]): row
            for row in table.get("verbs") or []
            if isinstance(row, dict) and isinstance(row.get("id"), int)
        }
        return registry, verbs

    def check(
        self,
        envelope_id: str,
        *,
        actor: str,
        verb: str,
        call_args: dict,
        now: datetime | None = None,
    ) -> dict:
        try:
            registry, verbs = self._registry()
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            return {"ok": False, "errno": "EAMBIG", "reason": str(exc)}
        matches = [
            row
            for row in registry.get("active") or []
            if isinstance(row, dict) and row.get("id") == envelope_id
        ]
        if len(matches) != 1:
            return {"ok": False, "errno": "ENOENT", "reason": "envelope not active"}
        envelope = matches[0]
        if envelope.get("issued_by") != "root":
            return {"ok": False, "errno": "EACCES", "reason": "issuer mismatch"}
        if envelope.get("revoked") or envelope.get("status") == "revoked":
            return {"ok": False, "errno": "EACCES", "reason": "envelope revoked"}
        if envelope.get("status") != "active":
            return {"ok": False, "errno": "ENOENT", "reason": "envelope inactive"}
        if not _granted(envelope.get("grantee"), actor):
            return {"ok": False, "errno": "EACCES", "reason": "grantee mismatch"}
        spec = verbs.get(envelope.get("verb_id"))
        if not spec or spec.get("verb") != envelope.get("verb") or verb != envelope.get("verb"):
            return {"ok": False, "errno": "EAMBIG", "reason": "verb mismatch"}
        bounds = envelope.get("bounds")
        if not isinstance(bounds, dict) or not isinstance(call_args, dict):
            return {"ok": False, "errno": "EAMBIG", "reason": "malformed bounds"}
        signature = set((spec.get("bounds") or {}).keys())
        # Registry v1.1 deliberately hoists metering fields from older verb rows.
        signature -= {"max_count", "expires_at"}
        if set(bounds) != signature:
            return {"ok": False, "errno": "EAMBIG", "reason": "bounds signature mismatch"}
        failed = sorted(set(call_args) - set(bounds)) + [
            key
            for key, granted in bounds.items()
            if key not in call_args or not _bound_matches(granted, call_args[key])
        ]
        if failed:
            return {"ok": False, "errno": "EAMBIG", "reason": "bounds mismatch", "fields": failed}
        try:
            expiry = _deadline(envelope.get("expires_at"))
        except ValueError as exc:
            return {"ok": False, "errno": "EAMBIG", "reason": str(exc)}
        if expiry and expiry <= (now or datetime.now(timezone.utc)):
            return {"ok": False, "errno": "EEXPIRED", "reason": "envelope expired"}
        maximum = envelope.get("max_count")
        if maximum is not None:
            if not isinstance(maximum, int) or isinstance(maximum, bool) or maximum < 0:
                return {"ok": False, "errno": "EAMBIG", "reason": "invalid max_count"}
            if envelope.get("use_count_source") != "frank":
                return {"ok": False, "errno": "EAMBIG", "reason": "untrusted meter"}
            used = self.ledger.citation_count(envelope_id)
            if used >= maximum:
                return {"ok": False, "errno": "EDQUOT", "used": used, "max_count": maximum}
        return {"ok": True, "envelope": envelope}

    def authorize_and_cite(
        self,
        envelope_id: str,
        *,
        actor: str,
        verb: str,
        call_args: dict,
        project: str,
        session: str,
    ) -> dict:
        result = self.check(
            envelope_id, actor=actor, verb=verb, call_args=call_args
        )
        outcome = "granted" if result.get("ok") else result.get("errno", "EAMBIG")
        content = {
            "envelope_id": envelope_id,
            "verb": verb,
            "call_args": call_args,
            "outcome": outcome,
            "session": session,
            "actor": actor,
        }
        maximum = (
            result.get("envelope", {}).get("max_count")
            if result.get("ok")
            else None
        )
        citation_id, final_outcome = self.ledger.append_citation(
            project,
            content,
            max_count=maximum,
        )
        if final_outcome == "EDQUOT" and result.get("ok"):
            result = {
                "ok": False,
                "errno": "EDQUOT",
                "reason": "envelope quota exhausted during atomic citation",
            }
        return {**result, "citation_id": citation_id, "cited_before_act": True}
