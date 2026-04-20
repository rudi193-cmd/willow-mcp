# willow-mcp

Agent-neutral MCP server. SQLite store (aligned with willow-1.7 WillowStore schema), Postgres knowledge base, Kart task queue. SAP/1.0 authorization on every tool call.

```bash
pip install willow-mcp
```

## v1.1.0 — Breaking changes

Store API now matches willow-1.7 `sap_mcp.py` exactly:
- `store_put`: takes `record` (JSON object) + optional `deviation` float — not `content` string
- `store_get` / `store_delete`: use `record_id` not `id`
- `store_list`: returns flat list, not `{items: [...]}`
- `store_update`: new tool
- `store_search`: multi-keyword AND (all tokens must match)
- Schema: `records` table with JSON blob, soft delete, deviation scoring
- `WILLOW_STORE_ROOT` shares SQLite files with willow-1.7 when set to the same path

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

```json
{
  "mcpServers": {
    "willow": {
      "command": "python3",
      "args": ["-m", "willow_mcp"]
    }
  }
}
```

On Sean's machine the global Claude Code config overrides this to `willow-1.7/sap_mcp.py` for full SAP access. The tool API is identical — apps work against both transparently.

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
