"""SOIL watchmen heartbeat — fleet layout parity with willow-2.0 loop_heartbeat."""
from __future__ import annotations

import json
import sqlite3
import time

import pytest

from willow_mcp import soil_heartbeat as sh


def test_soil_db_path_matches_fleet_layout(tmp_path):
    path = sh.soil_db_path("willow/loops/heartbeat", root=tmp_path)
    assert path == tmp_path / "willow" / "loops" / "heartbeat.db"


def test_write_watchmen_heartbeat_creates_fleet_record(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    sh.reset_throttle()
    assert sh.write_watchmen_heartbeat("kart_worker", interval_sec=60)
    db = sh.soil_db_path(sh.HEARTBEAT_SOIL_COLLECTION, root=tmp_path)
    row = sqlite3.connect(db).execute(
        "SELECT data FROM records WHERE id = ?", ("kart_worker",)
    ).fetchone()
    payload = json.loads(row[0])
    assert payload["tick_ok"] is True
    assert payload["interval_sec"] == 60
    assert "last_tick_at" in payload
    assert isinstance(payload["pid"], int)


def test_write_throttled_respects_interval(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    sh.reset_throttle()
    assert sh.write_throttled("kart_worker_batch") is True
    assert sh.write_throttled("kart_worker_batch") is False
    sh.reset_throttle("kart_worker_batch")
    assert sh.write_throttled("kart_worker_batch") is True


def test_soil_watchmen_heartbeat_maps_lane_to_key():
    beat = sh.SoilWatchmenHeartbeat("fast")
    assert beat.watchmen_key == "kart_worker"
    assert sh.watchmen_key_for_lane("batch") == "kart_worker_batch"


def test_soil_watchmen_heartbeat_callback_writes(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_STORE_ROOT", str(tmp_path))
    sh.reset_throttle()
    sh.SoilWatchmenHeartbeat("fast")(tick_ok=True)
    db = sh.soil_db_path(sh.HEARTBEAT_SOIL_COLLECTION, root=tmp_path)
    assert sqlite3.connect(db).execute(
        "SELECT 1 FROM records WHERE id = 'kart_worker'"
    ).fetchone()


def test_watchmen_key_rejects_unknown_lane():
    with pytest.raises(ValueError, match="fast\\|batch"):
        sh.watchmen_key_for_lane("priority")
