"""willow_mcp/safe_integration.py — Willow fleet integration point.

Answers WLWR1 R12 (SECURITY_AUDIT.md L-INT-01): without this module, willow-mcp
is an MCP server with no reverse channel — Willow cannot query its status or
lifecycle as a fleet member. status() is that channel.
"""
from . import __version__
from .db import get_pg


def _tools_registered() -> int:
    """Count of live @mcp.tool() registrations — read from the actual
    FastMCP tool manager rather than a hand-maintained constant, so this
    number can't silently drift when tools are added or removed."""
    from .server import mcp
    return len(mcp._tool_manager.list_tools())


def status() -> dict:
    """Return a lightweight liveness/identity snapshot for Willow orchestration."""
    pg = get_pg()
    return {
        "app_id": "willow-mcp",
        "version": __version__,
        "status": "running",
        "tools_registered": _tools_registered(),
        "postgres_reachable": pg is not None,
    }
