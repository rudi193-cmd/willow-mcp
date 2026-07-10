"""Tests for the_grove.py — rings, depth, canopy, deep roots, and the
status the next gardener will run first:

    $ python -m willow_mcp.the_grove --status
"""
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from willow_mcp import the_grove


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("WILLOW_HOME", str(tmp_path))
    monkeypatch.delenv("WILLOW_MCP_GROVE_RINGS", raising=False)
    return tmp_path


# ── rings ────────────────────────────────────────────────────────────────────

def test_bare_seedbed_has_no_depth_but_is_stable(home):
    assert the_grove.depth() == 0
    s = the_grove.status()
    assert s == {"stable": True, "depth": 0, "soil": "Worth tending."}


def test_rings_accumulate_and_persist(home):
    the_grove.add_ring("first rain", source="test")
    the_grove.add_ring("second rain")
    assert the_grove.depth() == 2
    stored = the_grove.rings()
    assert [r["lesson"] for r in stored] == ["first rain", "second rain"]
    assert [r["tick"] for r in stored] == [1, 2]
    assert stored[0]["source"] == "test"
    assert stored[0]["recorded_at"]  # a ring knows when the rain came


def test_a_ring_must_carry_a_lesson(home):
    with pytest.raises(ValueError):
        the_grove.add_ring("   ")
    assert the_grove.depth() == 0


def test_diseased_store_reads_empty_but_reports_unsettled(home):
    path = the_grove._rings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json")
    assert the_grove.rings() == []
    s = the_grove.status()
    assert s["stable"] is False
    assert s["soil"] == "Needs attention."


def test_rings_env_override(home, tmp_path, monkeypatch):
    alt = tmp_path / "elsewhere" / "rings.json"
    monkeypatch.setenv("WILLOW_MCP_GROVE_RINGS", str(alt))
    the_grove.add_ring("transplanted")
    assert json.loads(alt.read_text())["rings"][0]["lesson"] == "transplanted"


# ── canopy / deep roots ──────────────────────────────────────────────────────

def test_canopy_is_the_visible_architecture():
    seen = the_grove.canopy()
    for module in ("core", "the_grove", "tree_view", "server", "gate"):
        assert module in seen
    assert not any(name.startswith("_") for name in seen)


def test_deep_roots_are_the_recorded_lessons(home):
    assert the_grove.deep_roots() == []
    the_grove.add_ring("the loneliness")
    the_grove.add_ring("the systems")
    the_grove.add_ring("the things that persisted")
    assert the_grove.deep_roots() == [
        "the loneliness", "the systems", "the things that persisted"]


# ── status rendering / __main__ ──────────────────────────────────────────────

def test_render_status_shape(home):
    the_grove.add_ring("one")
    out = the_grove.render_status()
    assert out.splitlines() == [
        "The Grove is stable.",
        "Current depth: 1 ring.",
        "Soil health: Worth tending.",
    ]


def test_render_status_pluralizes(home):
    the_grove.add_ring("one")
    the_grove.add_ring("two")
    assert "Current depth: 2 rings." in the_grove.render_status()


def test_resting_display_knows_what_it_cannot_know(home):
    out = the_grove.render_resting()
    assert "Next gardener: unknown." in out
    assert "Chapters remaining: as many as the rain requires." in out


def test_module_runs_as_main_with_status(home):
    """The exact invocation the next gardener runs first:
    `python -m willow_mcp.the_grove --status` — a real subprocess, so the
    entry point, arg handling, and exit code are all exercised for real."""
    the_grove.add_ring("ran from the terminal")
    env = dict(os.environ, WILLOW_HOME=str(home),
               PYTHONPATH=str(Path(__file__).resolve().parents[1] / "src"))
    env.pop("WILLOW_MCP_GROVE_RINGS", None)
    proc = subprocess.run(
        [sys.executable, "-m", "willow_mcp.the_grove", "--status"],
        capture_output=True, text=True, env=env, timeout=30)
    assert proc.returncode == 0
    assert proc.stdout.splitlines() == [
        "The Grove is stable.",
        "Current depth: 1 ring.",
        "Soil health: Worth tending.",
    ]


def test_main_catches_broken_pipe(monkeypatch):
    """Same wrapper contract as server.main (see test_broken_pipe.py) — the
    status block is exactly the shape someone pipes into `grep -q`."""
    def _raise_broken_pipe(argv):
        raise BrokenPipeError()

    dup2_calls = []
    monkeypatch.setattr(the_grove, "_main", _raise_broken_pipe)
    monkeypatch.setattr(os, "dup2", lambda src, dst: dup2_calls.append((src, dst)))

    with pytest.raises(SystemExit) as exc_info:
        the_grove.main()
    assert exc_info.value.code == 0
    assert len(dup2_calls) == 1
