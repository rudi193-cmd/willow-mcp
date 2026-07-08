"""Tests for safe_integration.py — the Willow fleet reverse-integration point
(SECURITY_AUDIT.md L-INT-01). Previously untested."""

from willow_mcp import safe_integration


def test_status_shape():
    result = safe_integration.status()
    assert result["app_id"] == "willow-mcp"
    assert result["status"] == "running"
    assert isinstance(result["version"], str)
    assert isinstance(result["tools_registered"], int)
    assert isinstance(result["postgres_reachable"], bool)


def test_tools_registered_matches_live_fastmcp_registry():
    """Regression: tools_registered must reflect the actual registered tool
    count, not a hand-maintained constant that can silently drift."""
    from willow_mcp.server import mcp

    assert safe_integration._tools_registered() == len(mcp._tool_manager.list_tools())


def test_tools_registered_is_positive():
    assert safe_integration._tools_registered() > 0
