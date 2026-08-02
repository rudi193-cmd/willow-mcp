"""
willow-mcp — agent-neutral MCP server.

Provides: SQLite key/value store (SOIL), Postgres knowledge base, Kart task queue.
Auth: manifest-based per-tool ACL (app_id required on every tool call).
      HTTP serve mode adds OAuth 2.0 PKCE with Google / Apple upstream.

Run (stdio):  python3 -m willow_mcp
Run (HTTP):   python3 -m willow_mcp --serve --port 8765
"""

# Read from installed package metadata, not hardcoded. safe_integration.py
# reports this value outward to other systems, so a stale literal here is a
# wrong fact told to someone else — kartikeya's copy of this pattern had drifted
# three releases behind its own pyproject. Metadata is written at build time
# from the git tag and cannot drift.
try:
    from importlib.metadata import PackageNotFoundError, version as _pkg_version

    __version__ = _pkg_version("willow-mcp")
except PackageNotFoundError:  # running from a source tree with no install
    __version__ = "0.0.0+unknown"
