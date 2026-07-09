"""Worker liveness (Kart lift stage 4).

The property under test is the one an operator actually depends on: a `pending`
task with no live worker must read as *stranded*, and a healthy install that
never runs tasks must not read as *degraded*.
"""
import json
import os
import time

import pytest

from willow_mcp import heartbeat as hb


@pytest.fixture
def hb_root(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    return tmp_path / "worker_heartbeat"


def _write(root, name, **overrides):
    root.mkdir(parents=True, exist_ok=True)
    record = {"agent": "kart", "lane": "fast", "pid": os.getpid(),
              "host": hb.socket.gethostname(), "interval": 5.0,
              "tick_ok": True, "ts": time.time()}
    record.update(overrides)
    (root / name).write_text(json.dumps(record))
    return record


# ── writer ───────────────────────────────────────────────────────────────────

def test_heartbeat_writes_a_readable_record(hb_root):
    beat = hb.WorkerHeartbeat(agent="kart", lane="fast", interval=5.0)
    beat(lane="fast", tick_ok=True)
    assert beat.path.exists()
    record = json.loads(beat.path.read_text())
    assert record["pid"] == os.getpid()
    assert record["lane"] == "fast"
    assert record["tick_ok"] is True


def test_heartbeat_throttles_writes(hb_root):
    beat = hb.WorkerHeartbeat(interval=5.0)
    beat()
    first = beat.path.stat().st_mtime_ns
    beat()  # immediate second tick — the busy loop ticks twice a second
    assert beat.path.stat().st_mtime_ns == first


def test_heartbeat_leaves_no_tmp_file(hb_root):
    beat = hb.WorkerHeartbeat(interval=5.0)
    beat()
    assert list(hb_root.glob("*.tmp")) == []


def test_heartbeat_close_removes_the_file(hb_root):
    beat = hb.WorkerHeartbeat(interval=5.0)
    beat()
    beat.close()
    assert not beat.path.exists()
    assert hb.read_workers()["alive"] == 0


def test_heartbeat_never_raises_when_root_is_unwritable(hb_root, monkeypatch):
    """A telemetry failure must not kill a worker that is draining tasks fine."""
    beat = hb.WorkerHeartbeat(interval=5.0)
    monkeypatch.setattr(hb.Path, "mkdir", lambda *a, **k: (_ for _ in ()).throw(OSError("nope")))
    beat()  # must not raise
    assert not beat.path.exists()


# ── reader / classification ──────────────────────────────────────────────────

def test_read_workers_empty_when_no_root(hb_root):
    out = hb.read_workers()
    assert out == {"root": str(hb_root), "workers": [], "alive": 0, "status": "ok"}


def test_live_pid_with_fresh_tick_is_alive(hb_root):
    _write(hb_root, "kart-fast-1.json")
    out = hb.read_workers()
    assert out["alive"] == 1
    assert out["workers"][0]["state"] == "alive"


def test_dead_pid_is_dead_even_when_fresh(hb_root):
    """A forged or orphaned file naming a dead pid must never read `alive`."""
    _write(hb_root, "kart-fast-2.json", pid=999_999_998, ts=time.time())
    out = hb.read_workers()
    assert out["alive"] == 0
    assert out["workers"][0]["state"] == "dead"


def test_live_pid_with_old_tick_is_stale(hb_root):
    """Process still up, loop wedged — not alive, and distinguishable from dead."""
    _write(hb_root, "kart-fast-3.json", ts=time.time() - 120.0, interval=5.0)
    out = hb.read_workers()
    assert out["alive"] == 0
    assert out["workers"][0]["state"] == "stale"


def test_foreign_host_record_is_judged_on_age_alone(hb_root):
    """A pid is meaningless on another host — never probe an unrelated local process."""
    _write(hb_root, "kart-fast-4.json", host="some-other-box", pid=999_999_998)
    out = hb.read_workers()
    assert out["workers"][0]["state"] == "alive"


def test_stale_threshold_floors_at_30s(hb_root):
    assert hb.stale_after(0.0) == 30.0
    assert hb.stale_after(1.0) == 30.0
    assert hb.stale_after(20.0) == 60.0  # 3 missed idle ticks


def test_torn_file_is_skipped_not_fatal(hb_root):
    hb_root.mkdir(parents=True, exist_ok=True)
    (hb_root / "garbage.json").write_text("{not json")
    _write(hb_root, "kart-fast-5.json")
    out = hb.read_workers()
    assert out["status"] == "ok"
    assert out["alive"] == 1


def test_reap_removes_only_dead_records(hb_root):
    _write(hb_root, "alive.json")
    _write(hb_root, "dead.json", pid=999_999_998)
    assert hb.reap() == 1
    assert (hb_root / "alive.json").exists()
    assert not (hb_root / "dead.json").exists()


# ── diagnostic_summary rollup ────────────────────────────────────────────────

def test_pending_with_no_worker_is_a_warn():
    from willow_mcp import server
    worker = {"alive": 0, "pending": 3, "workers": []}
    problems = server._derive_problems({}, {}, {}, "stdio", worker)
    assert [p["check"] for p in problems] == ["worker"]
    assert problems[0]["severity"] == "warn"
    assert "willow-mcp worker" in problems[0]["fix"]


def test_pending_with_no_worker_names_the_stopped_workers():
    from willow_mcp import server
    worker = {"alive": 0, "pending": 1,
              "workers": [{"state": "dead", "pid": 4242}, {"state": "stale", "pid": 4243}]}
    detail = server._derive_problems({}, {}, {}, "stdio", worker)[0]["detail"]
    assert "4242" in detail and "4243" in detail


def test_no_worker_and_no_pending_is_not_a_problem():
    """The store/KB-only install. Absent worker + empty queue is healthy (B-18)."""
    from willow_mcp import server
    problems = server._derive_problems({}, {}, {}, "stdio", {"alive": 0, "pending": 0, "workers": []})
    assert problems == []
    assert server._derive_verdict(problems) == "ok"


def test_unknown_pending_never_raises_a_problem():
    """No Postgres / unconfirmed mapping → pending is None → don't guess."""
    from willow_mcp import server
    problems = server._derive_problems({}, {}, {}, "stdio", {"alive": 0, "pending": None, "workers": []})
    assert problems == []


def test_live_worker_with_pending_is_not_a_problem():
    from willow_mcp import server
    worker = {"alive": 1, "pending": 9, "workers": [{"state": "alive", "pid": 1}]}
    assert server._derive_problems({}, {}, {}, "stdio", worker) == []


def test_stranded_queue_degrades_the_verdict():
    from willow_mcp import server
    problems = server._derive_problems({}, {}, {}, "stdio", {"alive": 0, "pending": 2, "workers": []})
    assert server._derive_verdict(problems) == "degraded"


def test_derive_problems_worker_arg_is_optional():
    """Back-compat: existing callers pass four args."""
    from willow_mcp import server
    assert server._derive_problems({}, {}, {}, "stdio") == []
