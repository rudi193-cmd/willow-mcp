"""Tests for specialist_list / specialist_get MCP tools."""

import json

import pytest

from willow_mcp import home_init as hi
from willow_mcp import server


@pytest.fixture
def reader_app(home):
    app_dir = home / "mcp_apps" / "desk"
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["dispatch_read"]})
    )
    hi.ensure_home_layout()
    return "desk"


def test_specialist_list(reader_app):
    out = server.specialist_list(reader_app)
    assert out["total"] >= 6
    assert any(s["agent_id"] == "hanuman" for s in out["specialists"])


def test_specialist_get(reader_app):
    out = server.specialist_get(reader_app, "ada")
    assert out["agent_id"] == "ada"
    assert "persona" in out
    assert "Ada" in out["persona"]


def test_specialist_get_not_found(reader_app):
    out = server.specialist_get(reader_app, "nobody")
    assert out["error"] == "not_found"
