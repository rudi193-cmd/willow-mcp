"""Tests for willow_mcp.mai.tools — the MarkdownAI (mai) tools.

Vendored from willow-2.0 (sap/mai); adapted here to the willow_mcp package.
The willow-2.0 original also had a test coupling mai to that repo's fylgja
pre_tool hook — dropped, since that hook is not part of the vendored tool.

#161: the tools are manifest-gated, so these tests run as a granted app
("maitest", markdownai_read + markdownai_write). Denial-path coverage lives
in tests/test_mai_directive_gate.py.
"""
from __future__ import annotations

import asyncio
import json

import pytest

from willow_mcp.mai import tools as mai_tools

_APP = "maitest"


@pytest.fixture(autouse=True)
def granted_app(tmp_path, monkeypatch):
    apps_root = tmp_path / "mcp_apps"
    app_dir = apps_root / _APP
    app_dir.mkdir(parents=True)
    (app_dir / "manifest.json").write_text(
        json.dumps({"permissions": ["markdownai_read", "markdownai_write"]})
    )
    monkeypatch.setenv("WILLOW_MCP_APPS_ROOT", str(apps_root))
    return apps_root


def _register():
    from mcp.server.fastmcp import FastMCP

    m = FastMCP("test-mai")
    mai_tools.register(m)
    return m


def test_registry_lists_ten_mai_tools():
    m = _register()
    names = [t.name for t in asyncio.run(m.list_tools()) if t.name.startswith("mai_")]
    assert "mai_write_file" in names
    assert "mai_read_file" in names
    assert len(names) == 10


def test_mai_write_file_on_disk(tmp_path):
    path = tmp_path / "doc.md"
    content = "@markdownai v1.0\n\n# Test\n\nHello.\n"
    m = _register()
    result = asyncio.run(
        m.call_tool("mai_write_file", {"path": str(path), "content": content, "app_id": _APP})
    )
    assert '"ok": true' in str(result[0]) or "ok': True" in str(result[0])
    assert path.read_text(encoding="utf-8") == content


def test_markdownai_detected_after_yaml_frontmatter():
    raw = "---\nagent: hanuman\ndate: 2026-05-28\n---\n\n@markdownai v1.0\n\n# Hi\n"
    assert mai_tools._is_markdownai_content(raw)
    assert mai_tools._markdownai_body(raw).startswith("@markdownai")


def test_write_guard_keeps_header(tmp_path):
    path = tmp_path / "keep.md"
    path.write_text("@markdownai v1.0\n\nOld\n", encoding="utf-8")
    assert mai_tools._is_markdownai_path(path)
    assert not mai_tools._is_markdownai_content("plain markdown without header")


def test_read_renders_ai_format(tmp_path):
    """A @markdownai doc renders (header stripped, @prompt blocks removed)."""
    path = tmp_path / "r.md"
    path.write_text(
        "@markdownai v1.0\n\n# Title\n\n@prompt\nhidden instruction\n@end\n\nVisible.\n",
        encoding="utf-8",
    )
    m = _register()
    out = str(asyncio.run(m.call_tool("mai_read_file", {"path": str(path), "app_id": _APP})))
    assert "Visible." in out
    assert "@markdownai" not in out
    assert "hidden instruction" not in out


def _result(call_result):
    """FastMCP call_tool returns (content_blocks, structured); list-returning
    tools wrap the list under structured['result']."""
    structured = call_result[1] if isinstance(call_result, tuple) else call_result
    return structured["result"] if isinstance(structured, dict) and "result" in structured else structured


def test_phases_and_constraints(tmp_path):
    path = tmp_path / "p.md"
    path.write_text(
        "@markdownai v1.0\n\n@phase one\nfirst\n\n@phase two\nsecond\n\n"
        "@constraint severity=critical never delete\n@constraint severity=info be kind\n",
        encoding="utf-8",
    )
    m = _register()
    phases = _result(asyncio.run(m.call_tool("mai_list_phases", {"file": str(path), "app_id": _APP})))
    assert [p["name"] for p in phases] == ["one", "two"]
    cons = _result(asyncio.run(m.call_tool("mai_get_constraints", {"file": str(path), "app_id": _APP})))
    assert cons[0]["severity"] == "critical"  # sorted most-severe first
