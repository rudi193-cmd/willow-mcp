"""Interactive operator-only writer for canonical consent and its mirror."""
from __future__ import annotations

import fcntl
import hashlib
import json
import os
import stat
import sys
import tempfile
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from . import consent


def _require_operator_terminal() -> None:
    # Non-forgeable operator boundary (§4.3): not in Kart, and a real
    # operator-owned controlling terminal — not just isatty().
    from .human_session import require_operator_terminal

    require_operator_terminal()


def _trusted(path: Path) -> None:
    if path.is_symlink() or path.parent.is_symlink():
        raise PermissionError(f"symlinked policy path refused: {path}")
    target = path if path.exists() else path.parent
    if not target.exists():
        target.mkdir(parents=True, mode=0o700)
        target.chmod(0o700)
    info = target.stat()
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
        raise PermissionError(f"untrusted ownership or permissions: {target}")
    if path.exists():
        info = path.stat()
        if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) & 0o022:
            raise PermissionError(f"untrusted ownership or permissions: {path}")


def _atomic_json(path: Path, data: dict) -> None:
    _trusted(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(name, 0o600)
        os.replace(name, path)
    finally:
        Path(name).unlink(missing_ok=True)


@contextmanager
def _exclusive(dir_path: Path):
    """Serialize consent writers (§4.4): a crash- and concurrency-safe update of
    canonical+mirror+audit must not interleave with another operator's. An
    ``flock`` on a lockfile beside the canonical file makes the whole
    read-modify-write sequence one critical section; the lock releases on close
    (and on process death), so a crashed writer never wedges the next one."""
    dir_path.mkdir(parents=True, exist_ok=True)
    fd = os.open(dir_path / ".consent.lock", os.O_WRONLY | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd, fcntl.LOCK_UN)
        os.close(fd)


def _digest(data: dict) -> str:
    return hashlib.sha256(
        json.dumps(data, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _append_audit(path: Path, event: dict) -> None:
    _trusted(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    os.chmod(path, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(json.dumps(event, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def write_consent(values: dict[str, bool], *, action: str = "set") -> dict:
    _require_operator_terminal()
    if set(values) != set(consent.CONSENT_KEYS) or not all(
        type(value) is bool for value in values.values()
    ):
        raise ValueError("consent requires exactly internet/cloud_llm/lan booleans")
    canonical_path, mirror_path = consent.settings_path(), consent.legacy_path()
    # One critical section for the whole read-modify-write across canonical,
    # mirror, and audit (§4.4) — no interleaving with a concurrent operator.
    with _exclusive(canonical_path.parent):
        before = consent.read_consent()
        if before.get("status") == "fail":
            raise ValueError("canonical consent is malformed; refusing to replace it")
        settings = {}
        if canonical_path.is_file():
            try:
                settings = json.loads(canonical_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                settings = {}
        if not isinstance(settings, dict):
            settings = {}
        audit_path = canonical_path.parent / "audit" / "consent.jsonl"
        audit = {
            "at": datetime.now(timezone.utc).isoformat(),
            "actor_uid": os.geteuid(),
            "action": action,
            "changed_keys": [
                key
                for key in consent.CONSENT_KEYS
                if before["consent"].get(key) != values[key]
            ],
            "before_hash": _digest(before["consent"]),
            "after_hash": _digest(values),
            "canonical": str(canonical_path),
            "mirror": str(mirror_path),
        }
        # Intent-before-commit: the audit records what is about to change *before*
        # the files move, so a crash between canonical and mirror is recoverable
        # (canonical is source of truth; consent.read_consent reconciles the
        # mirror on read) and never silent.
        _append_audit(audit_path, {**audit, "phase": "intent"})
        settings["consent"] = dict(values)
        _atomic_json(canonical_path, settings)
        _atomic_json(mirror_path, dict(values))
        after = consent.read_consent()
        result = {
            **audit,
            "phase": "committed",
            "reconciled": after.get("disagreement") is None,
        }
        _append_audit(audit_path, result)
        return result


def set_key(key: str, value: bool) -> dict:
    if key not in consent.CONSENT_KEYS or type(value) is not bool:
        raise ValueError("key/value must be a known consent key and strict boolean")
    current = consent.read_consent()["consent"]
    current[key] = value
    return write_consent(current, action=f"set:{key}")


def reconcile() -> dict:
    current = consent.read_consent()
    if current.get("status") == "fail":
        raise ValueError("canonical consent is malformed; refusing to guess intent")
    return write_consent(current["consent"], action="reconcile")
