"""Resource-cap regression tests for the willow-mcp → kartikeya execution path.

Dispatch 910391C3: tasks drained by PgTaskQueue execute via kartikeya's
`sandbox.run_shell` (caps on by default). These tests witness cgroup leaf
placement, rlimit fallback, and leaf cleanup on the builder host.
"""
from __future__ import annotations

import glob
import os

import pytest

from kartikeya import cgroup_setup, sandbox

_CGROUP_PROBE = r"""
CG=$(awk -F: '$2=="" {print $3}' /proc/self/cgroup)
echo "CGROUP=${CG}"
M="/sys/fs/cgroup${CG}/memory.max"
P="/sys/fs/cgroup${CG}/pids.max"
test -f "$M" && echo "MEM=$(cat "$M")"
test -f "$P" && echo "PIDS=$(cat "$P")"
""".strip()

_MEM_2G = str(2 * 1024**3)
_PIDS_DEFAULT = "512"


def _delegated_parent() -> str | None:
    return cgroup_setup.resolve_cgroup_parent()


@pytest.fixture
def delegated_parent():
    parent = _delegated_parent()
    if not parent:
        pytest.skip("no delegated kart.slice parent on this host")
    return parent


def test_pg_task_queue_subclasses_task_queue():
    from kartikeya.queue import TaskQueue

    from willow_mcp import task_queue as tq

    assert issubclass(tq.PgTaskQueue, TaskQueue)
    assert tq.WillowMcpTaskQueue is tq.PgTaskQueue


def test_run_shell_places_task_in_kart_cgroup_leaf(delegated_parent):
    result = sandbox.run_shell(_CGROUP_PROBE, timeout=30)
    assert result.get("returncode") == 0, result
    assert result.get("resource_limit") == "cgroup"
    out = result.get("stdout") or ""
    assert "kart.slice/kart-" in out
    assert f"MEM={_MEM_2G}" in out
    assert f"PIDS={_PIDS_DEFAULT}" in out


def test_run_shell_falls_back_to_rlimit_without_delegated_parent(monkeypatch):
    # Plain sandbox path — CI runners lack bubblewrap; kartikeya uses the same
    # env switch for rlimit integration tests (tests/test_sandbox.py).
    monkeypatch.setenv("WILLOW_KART_NO_BWRAP", "1")
    monkeypatch.setattr(cgroup_setup, "resolve_cgroup_parent", lambda: None)
    monkeypatch.delenv("KART_CGROUP_PARENT", raising=False)
    result = sandbox.run_shell("echo rlimit-ok", timeout=30)
    assert result.get("returncode") == 0, result
    assert result.get("resource_limit") == "rlimit"
    assert (result.get("stdout") or "").strip() == "rlimit-ok"


def test_cgroup_leaf_removed_after_task(delegated_parent):
    before = set(glob.glob(os.path.join(delegated_parent, "kart-*")))
    result = sandbox.run_shell("echo cleanup-ok", timeout=30)
    assert result.get("returncode") == 0, result
    after = set(glob.glob(os.path.join(delegated_parent, "kart-*")))
    assert after == before
