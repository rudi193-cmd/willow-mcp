"""Tests for remote enforcement posture (#164)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from willow_mcp import enforcement_posture as ep


def test_hooks_registered_detects_pre_tool_use(tmp_path: Path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(
        json.dumps(
            {
                "hooks": {
                    "PreToolUse": [
                        {
                            "hooks": [
                                {"command": "python3 hooks/pre_tool_use.py"},
                            ]
                        }
                    ]
                }
            }
        ),
        encoding="utf-8",
    )
    assert ep.hooks_registered(tmp_path)


def test_hooks_registered_false_when_missing(tmp_path: Path):
    assert not ep.hooks_registered(tmp_path)


def test_mcp_configured_requires_willow_home_env(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps(
            {
                "mcpServers": {
                    "willow-mcp": {
                        "command": ".venv/bin/python3",
                        "args": ["-m", "willow_mcp"],
                        "env": {"WILLOW_HOME": str(tmp_path / ".willow")},
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    assert ep.mcp_configured(tmp_path)


def test_mcp_configured_false_without_env_block(tmp_path: Path):
    (tmp_path / ".mcp.json").write_text(
        json.dumps({"mcpServers": {"willow-mcp": {"args": ["-m", "willow_mcp"]}}}),
        encoding="utf-8",
    )
    assert not ep.mcp_configured(tmp_path)


def test_assess_mcp_live_requires_hooks_mcp_and_ok_verdict(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ep, "hooks_registered", lambda _p: True)
    monkeypatch.setattr(ep, "mcp_configured", lambda _p: True)
    monkeypatch.setattr(ep, "diagnostic_verdict", lambda **_: ("ok", None))
    posture = ep.assess(
        project_dir=tmp_path,
        willow_home=tmp_path / ".willow",
        app_id="willow",
        remote=True,
    )
    assert posture["mcp_live"] is True


def test_assess_mcp_live_false_on_degraded_only_when_verdict_not_ok(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ep, "hooks_registered", lambda _p: True)
    monkeypatch.setattr(ep, "mcp_configured", lambda _p: True)
    monkeypatch.setattr(ep, "diagnostic_verdict", lambda **_: ("broken", None))
    posture = ep.assess(
        project_dir=tmp_path,
        willow_home=tmp_path / ".willow",
        app_id="willow",
        remote=True,
    )
    assert posture["mcp_live"] is False


def test_assess_accepts_degraded_verdict(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(ep, "hooks_registered", lambda _p: True)
    monkeypatch.setattr(ep, "mcp_configured", lambda _p: True)
    monkeypatch.setattr(ep, "diagnostic_verdict", lambda **_: ("degraded", None))
    posture = ep.assess(
        project_dir=tmp_path,
        willow_home=tmp_path / ".willow",
        app_id="willow",
        remote=True,
    )
    assert posture["mcp_live"] is True


def test_write_and_load_marker_round_trip(tmp_path: Path):
    wh = tmp_path / ".willow"
    posture = {"schema": 1, "mcp_live": False}
    path = ep.write_marker(posture, willow_home=wh)
    assert path.exists()
    loaded = ep.load_marker(willow_home=str(wh))
    assert loaded == posture


def test_banner_names_missing_hooks():
    text = ep.banner({"mcp_live": False, "hooks_registered": False, "mcp_configured": True})
    assert "PreToolUse" in text
    assert "MCP GATE NOT LIVE" in text
