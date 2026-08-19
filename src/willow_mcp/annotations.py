"""
MCP tool annotations — single source of truth for all tool-hosting modules.

Each constant is a dict passed to ``@mcp.tool(annotations=...)``.  Clients use
the hints to distinguish read-only, write, destructive, idempotent, and
external-facing operations without calling the tool first.
"""

ANNO_READ: dict = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": False}
ANNO_READ_OPEN: dict = {"readOnlyHint": True, "destructiveHint": False, "openWorldHint": True}
ANNO_WRITE: dict = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": False}
ANNO_WRITE_IDEM: dict = {"readOnlyHint": False, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
ANNO_DESTRUCTIVE: dict = {"readOnlyHint": False, "destructiveHint": True, "openWorldHint": False}
ANNO_WRITE_OPEN: dict = {"readOnlyHint": False, "destructiveHint": False, "openWorldHint": True}
