"""willow_mcp/safe_integration.py — Willow fleet integration point.

Answers WLWR1 R12 (SECURITY_AUDIT.md L-INT-01): without this module, willow-mcp
is an MCP server with no reverse channel — Willow cannot query its status or
lifecycle as a fleet member. status() is that channel.
"""
from . import __version__
from .db import get_pg

# Kept in sync by hand with the @mcp.tool() definitions in server.py — update
# this count when tools are added or removed.
_TOOLS_REGISTERED = 20


def status() -> dict:
    """Return a lightweight liveness/identity snapshot for Willow orchestration."""
    pg = get_pg()
    return {
        "app_id": "willow-mcp",
        "version": __version__,
        "status": "running",
        "tools_registered": _TOOLS_REGISTERED,
        "postgres_reachable": pg is not None,
    }
