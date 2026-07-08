# willow-mcp

[![PyPI](https://img.shields.io/pypi/v/willow-mcp)](https://pypi.org/project/willow-mcp/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![MCP](https://img.shields.io/badge/MCP-1.0-blue)](https://modelcontextprotocol.io)

Agent-neutral MCP server with persistent memory and task execution. Works with any MCP client: Claude Code, Claude Desktop, Cursor, or any custom agent that speaks stdio MCP.

**Three storage backends in one server:**
- **SOIL store** — SQLite-backed local key/value store with full-text search and soft delete
- **Postgres knowledge base** — multi-keyword searchable knowledge graph
- **Kart task queue** — sandboxed task executor for shell commands and scripts

Every tool call is authorized via [SAP/1.0](https://github.com/rudi193-cmd/sap-rfc) — a filesystem-based identity gate with no ACL database.

## Install

```bash
pip install willow-mcp
```

Requires Python 3.11+. Postgres is optional — SOIL store works standalone.

## Tools

| Tool | Description |
|------|-------------|
| `store_put` | Write record (JSON object) to SQLite store |
| `store_get` | Read record by `record_id` |
| `store_list` | List all records in a collection |
| `store_update` | Update an existing record |
| `store_search` | Multi-keyword AND search in a collection |
| `store_delete` | Soft-delete a record by `record_id` |
| `store_search_all` | Search across all collections |
| `knowledge_ingest` | Add to Postgres knowledge base |
| `knowledge_search` | Multi-keyword search in Postgres knowledge base |
| `task_submit` | Submit task to Kart queue |
| `task_status` | Check task status |
| `task_list` | List pending tasks |

Every tool requires an `app_id` param. Authorization is checked via [SAP/1.0](https://github.com/rudi193-cmd/sap-rfc).

## MCP config

Repo-local configs (`.cursor/mcp.json`, `.mcp.json`) wire **willow-mcp** plus
**codebase-memory-mcp** for graph-augmented code search while developing this
package. Install the CBM binary to `~/.local/bin/codebase-memory-mcp`, then
index this repo (`project: home-sean-campbell-github-willow-mcp`).

`willow-mcp`'s entry points at a repo-local venv rather than a bare `python3` —
your host interpreter may not have `pip` or the `mcp` package installed (a
missing import here crashes the stdio server before the handshake, which
shows up as a client-side reconnect failure). Set it up once per clone:

```bash
python3 -m venv .venv
.venv/bin/python3 -m pip install -e .
```

Minimal single-server config (path is relative to the repo root, so this
works unmodified on any clone once the venv above exists):

```json
{
  "mcpServers": {
    "willow-mcp": {
      "type": "stdio",
      "command": ".venv/bin/python3",
      "args": ["-m", "willow_mcp"]
    },
    "codebase-memory-mcp": {
      "type": "stdio",
      "command": "codebase-memory-mcp",
      "args": []
    }
  }
}
```

Point `WILLOW_PG_DB` / `WILLOW_STORE_ROOT` at your host fleet store when you
need Postgres knowledge or shared SOIL data.

You can also run the full [willow-2.0](https://github.com/rudi193-cmd/willow-2.0) server directly — the tool API is identical, apps work against both transparently.

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `WILLOW_PG_DB` | `willow` | Postgres database name |
| `WILLOW_PG_USER` | `$USER` | Postgres user (Unix socket auth) |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | SQLite store directory — set to willow-1.7's store root to share data |
| `WILLOW_APP_ID` | `willow-mcp` | Default app_id if not passed per-call |
| `SAP_SAFE_ROOT` | `~/.sap/Applications` | SAFE folder root |
| `SAP_PGP_FINGERPRINT` | *(empty)* | Pinned GPG fingerprint |

## Authorization

Uses [openclaw-sap-gate](https://github.com/rudi193-cmd/openclaw-sap-gate) (SAP/1.0). If `openclaw-sap-gate` is not installed, all calls are permitted (open mode).

## License

MIT — Sean Campbell 2026
