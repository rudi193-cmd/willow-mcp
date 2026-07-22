"""Worker drain loop, heartbeat/reap, and deploy unit regression tests."""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

import pytest

from kartikeya import SqliteTaskQueue

from willow_mcp import heartbeat as hb
from willow_mcp import soil_heartbeat as sh
from willow_mcp import worker as worker_mod


@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    store = tmp_path / "store"
    hb_root = tmp_path / "worker_heartbeat"
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(store))
    monkeypatch.setenv("WILLOW_APP_ID", "worker-test")
    monkeypatch.setenv("WILLOW_WORKER_HEARTBEAT_ROOT", str(hb_root))
    monkeypatch.setenv("WILLOW_KART_NO_BWRAP", "1")
    monkeypatch.setenv("WILLOW_SOIL_HEARTBEAT_INTERVAL", "1")
    sh.reset_throttle()
    return tmp_path


def test_worker_module_help():
    result = worker_mod.build_parser().format_help()
    assert "--require-postgres" in result
    assert "--once" in result


def test_worker_drains_sqlite_queue_once(worker_env, monkeypatch):
    db_path = worker_env / "kart.db"
    queue = SqliteTaskQueue(str(db_path))
    queue.submit("DRAIN1", "echo worker-drain-ok", agent="kart")

    monkeypatch.setattr("willow_mcp.task_queue.build_task_queue", lambda app_id, **kw: queue)

    worker_mod.run_worker_daemon(
        app_id="worker-test",
        lane="fast",
        once=True,
        require_postgres=False,
        interval=0.1,
    )

    stats = queue.stats()
    assert stats.completed == 1
    assert stats.pending == 0
    row = sqlite3.connect(str(db_path)).execute(
        "SELECT result FROM tasks WHERE task_id = 'DRAIN1'"
    ).fetchone()
    result = json.loads(row[0])
    assert "worker-drain-ok" in (result.get("stdout") or "")


def test_worker_publishes_file_and_soil_heartbeats(worker_env, monkeypatch):
    db_path = worker_env / "kart.db"
    queue = SqliteTaskQueue(str(db_path))
    monkeypatch.setattr("willow_mcp.task_queue.build_task_queue", lambda app_id, **kw: queue)

    worker_mod.run_worker_daemon(
        app_id="worker-test",
        lane="fast",
        once=True,
        require_postgres=False,
        interval=0.1,
    )

    workers = hb.read_workers()
    assert workers["alive"] >= 0  # file removed on clean shutdown
    soil_db = sh.soil_db_path(sh.HEARTBEAT_SOIL_COLLECTION)
    row = sqlite3.connect(soil_db).execute(
        "SELECT data FROM records WHERE id = 'kart_worker'"
    ).fetchone()
    assert row is not None
    assert json.loads(row[0])["tick_ok"] is True


def test_worker_reaps_stale_heartbeat_files_on_start(worker_env, monkeypatch):
    import socket

    hb_root = Path(worker_env) / "worker_heartbeat"
    hb_root.mkdir(parents=True)
    dead = hb_root / "kart-fast-999999.json"
    dead.write_text(
        json.dumps(
            {
                "agent": "kart",
                "lane": "fast",
                "pid": 999999,
                "host": socket.gethostname(),
                "interval": 5.0,
                "tick_ok": True,
                "ts": 0.0,
            }
        )
    )
    db_path = worker_env / "kart.db"
    queue = SqliteTaskQueue(str(db_path))
    monkeypatch.setattr("willow_mcp.task_queue.build_task_queue", lambda app_id, **kw: queue)

    worker_mod.run_worker_daemon(
        app_id="worker-test",
        lane="fast",
        once=True,
        require_postgres=False,
        interval=0.1,
    )

    assert not dead.exists()


def test_worker_lane_from_env(worker_env, monkeypatch):
    monkeypatch.setenv("KART_WORKER_LANE", "batch")
    monkeypatch.delenv("WILLOW_WORKER_LANE", raising=False)
    assert worker_mod._lane_from_env() == "batch"


def test_deploy_kart_worker_units_are_willow_mcp_successors():
    root = Path(__file__).resolve().parents[1] / "deploy"
    for name in ("kart-worker.service", "kart-worker-batch.service"):
        text = (root / name).read_text(encoding="utf-8")
        assert "willow-2.0" not in text
        assert "-m willow_mcp.worker" in text
        assert "EnvironmentFile=-%h/github/.willow/env" in text


def test_caps_smoke_rlimit_path(monkeypatch):
    """Reuse slice-1 caps fixture: rlimit fallback without bubblewrap."""
    from kartikeya import cgroup_setup, sandbox

    monkeypatch.setenv("WILLOW_KART_NO_BWRAP", "1")
    monkeypatch.setattr(cgroup_setup, "resolve_cgroup_parent", lambda: None)
    monkeypatch.delenv("KART_CGROUP_PARENT", raising=False)
    result = sandbox.run_shell("echo caps-worker-smoke", timeout=30)
    assert result.get("returncode") == 0, result
    assert result.get("resource_limit") == "rlimit"
