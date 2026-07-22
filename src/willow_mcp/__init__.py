"""
willow-mcp — agent-neutral MCP server.

Provides: SQLite key/value store (SOIL), Postgres knowledge base, Kart task queue.
Auth: manifest-based per-tool ACL (app_id required on every tool call).
      HTTP serve mode adds OAuth 2.0 PKCE with Google / Apple upstream.

Run (stdio):  python3 -m willow_mcp
Run (HTTP):   python3 -m willow_mcp --serve --port 8765
"""

__version__ = "2.0.1"
