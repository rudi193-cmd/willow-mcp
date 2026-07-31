"""Best-effort Postgres recovery when the local cluster dies (#160).

Opt-in via ``WILLOW_MCP_ENSURE_POSTGRES=1`` — willow-mcp must not start system
services on installs that never asked for it.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import time


def ensure_enabled() -> bool:
    return os.environ.get("WILLOW_MCP_ENSURE_POSTGRES", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def _pg_isready() -> bool:
    if not shutil.which("pg_isready"):
        return False
    try:
        proc = subprocess.run(
            ["pg_isready", "-q"],
            capture_output=True,
            timeout=5,
        )
        return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False


def _start_commands() -> list[list[str]]:
    cmds: list[list[str]] = []
    cluster = os.environ.get("WILLOW_PG_CLUSTER", "16/main")
    if shutil.which("pg_ctlcluster"):
        parts = cluster.split("/", 1)
        if len(parts) == 2:
            cmds.append(["pg_ctlcluster", parts[0], parts[1], "start"])
    if shutil.which("service"):
        cmds.append(["service", "postgresql", "start"])
    return cmds


def try_recover(*, wait_seconds: float = 8.0) -> bool:
    """If Postgres is down, try local start helpers then wait for readiness."""
    if _pg_isready():
        return True
    for cmd in _start_commands():
        try:
            subprocess.run(cmd, capture_output=True, timeout=30, check=False)
        except (OSError, subprocess.TimeoutExpired):
            continue
        deadline = time.monotonic() + wait_seconds
        while time.monotonic() < deadline:
            if _pg_isready():
                return True
            time.sleep(0.25)
    return _pg_isready()
