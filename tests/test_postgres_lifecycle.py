"""Postgres ensure/recover seam (#160)."""

from unittest import mock

from willow_mcp import postgres_lifecycle as pl


def test_ensure_disabled_by_default(monkeypatch):
    monkeypatch.delenv("WILLOW_MCP_ENSURE_POSTGRES", raising=False)
    assert pl.ensure_enabled() is False


def test_try_recover_noop_when_ready(monkeypatch):
    monkeypatch.setenv("WILLOW_MCP_ENSURE_POSTGRES", "1")
    monkeypatch.setattr(pl, "_pg_isready", lambda: True)
    assert pl.try_recover() is True


def test_try_recover_starts_when_down(monkeypatch):
    monkeypatch.setattr(pl, "_start_commands", lambda: [["echo", "start"]])
    calls = {"n": 0}

    def ready():
        calls["n"] += 1
        return calls["n"] >= 2

    monkeypatch.setattr(pl, "_pg_isready", ready)
    with mock.patch("subprocess.run") as run:
        assert pl.try_recover(wait_seconds=1.0) is True
        run.assert_called()
