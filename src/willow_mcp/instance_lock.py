"""instance_lock — willow-mcp declares itself SINGLE-INSTANCE in serve mode.

The undeclared assumption, made declared and enforced.

MCP 2026-07-28 (SEP-2567) removes `Mcp-Session-Id` and protocol-level sessions:
*"any server instance can handle any stateless request."* That is true of the
PROTOCOL. It is not true of this server. Load-bearing state lives in process
memory here — the bound-agent sessions (`session_binder.SessionBinder._sessions`),
the rate limiter's token buckets (`server._buckets`), and the OAuth provider's
in-flight authorize/callback state (`oauth.GroveOAuthProvider._pending`, `._codes`,
`._code_identity`). None of it is shared, and each of them fails a *different*
way when a request lands on the replica that does not hold it. The full inventory,
the failure of each, and the migration order are in
`docs/design/stateless-session-state.md`.

So: **one serve-mode process per `$WILLOW_HOME`.** This module is where that is
written down and where it is enforced, because a second serve process is silent —
it starts fine, answers requests, and the damage shows up later as an agent that
cannot bind or a human whose login "failed".

Scope, deliberately narrow:

* **serve mode only.** Multiple *stdio* processes over one `$WILLOW_HOME` are
  normal and supported (a desktop client and a terminal, plus every `willow-mcp`
  CLI invocation) — they are separate agents with separate sessions, not replicas
  of one. Their shared state is on disk and must be made process-safe there;
  see the receipt-log chain fix in `receipts.py` for the first of those.
* **same `$WILLOW_HOME` only.** Two serve processes over two different homes are
  two installs and never collide; they take two different lock files.

The lock is `flock(LOCK_EX | LOCK_NB)`, not a PID file, for one reason: the
kernel releases it when the holder dies — SIGKILL, OOM, power loss, container
eviction included. There is no stale lock to clean up and no "is PID 4211 still
the server or is it now someone's editor" guess to get wrong.
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Optional

from . import paths

log = logging.getLogger(__name__)

#: Set to a truthy value to start anyway. Named "unsafe" on purpose — it does not
#: make a second instance work, it only stops this module from saying no.
OVERRIDE_ENV = "WILLOW_MCP_UNSAFE_MULTI_INSTANCE"

LOCK_FILENAME = "serve.lock"


class InstanceLockError(RuntimeError):
    """A second serve-mode process tried to start on a $WILLOW_HOME already served."""


def lock_path(home: Optional[Path] = None) -> Path:
    return (Path(home) if home is not None else paths.willow_home()) / LOCK_FILENAME


def _override_enabled() -> bool:
    return os.environ.get(OVERRIDE_ENV, "").strip().lower() in ("1", "true", "yes", "on")


def acquire(home: Optional[Path] = None):
    """Take the single-serve-instance lock for `$WILLOW_HOME`.

    Returns the open lock file on success — **the caller must keep the returned
    object alive for the process lifetime**; dropping it closes the fd and
    releases the lock. Returns None when the guard is inapplicable (no `fcntl`)
    or overridden.

    Raises `InstanceLockError` if another live process already serves this home.
    """
    try:
        import fcntl
    except ImportError:                                   # pragma: no cover - POSIX only
        # No advisory locking available (Windows). Do not fail the start over a
        # guard: say plainly that the assumption is now unenforced rather than
        # pretending it was checked.
        log.warning("instance guard unavailable on this platform (no fcntl) — "
                    "willow-mcp is single-instance per WILLOW_HOME and nothing here checks it")
        return None

    path = lock_path(home)
    path.parent.mkdir(parents=True, exist_ok=True)
    # Opened "a+", never truncated on open: truncating would blank the previous
    # holder's diagnostics before we know whether we may take the lock.
    handle = path.open("a+")
    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.seek(0)
        holder = handle.read().strip() or "unknown"
        handle.close()
        if _override_enabled():
            log.warning(
                "%s is set: starting a SECOND serve instance on %s (held by %s). "
                "Agent bindings, rate limits and OAuth logins are per-process and "
                "WILL fail for whichever replica does not hold them — see "
                "docs/design/stateless-session-state.md.",
                OVERRIDE_ENV, path.parent, holder)
            return None
        raise InstanceLockError(
            f"another willow-mcp serve process already holds {path} ({holder}).\n"
            f"willow-mcp is single-instance per WILLOW_HOME: agent sessions, rate-limit\n"
            f"buckets and in-flight OAuth state live in process memory, so a second\n"
            f"instance does not share the load — it silently breaks agent binding\n"
            f"(session_bind on one, tool calls refused by the other) and human login\n"
            f"(authorize on one, IdP callback rejected by the other).\n"
            f"Run one server, or give this one its own WILLOW_HOME.\n"
            f"See docs/design/stateless-session-state.md."
        )

    # Record who holds it, for the next process's error message. Best-effort: a
    # failed diagnostic write must never drop a lock we legitimately hold.
    try:
        handle.seek(0)
        handle.truncate()
        handle.write(f"pid={os.getpid()}\n")
        handle.flush()
    except OSError:                                       # pragma: no cover
        pass
    return handle
