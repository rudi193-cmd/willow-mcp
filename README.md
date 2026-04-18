# willow-mcp

Agent-neutral MCP server. SQLite key/value store, Postgres knowledge base, Kart task queue. SAP/1.0 authorization on every tool call.

```bash
pip install willow-mcp
```

## Tools

| Tool | Description |
|------|-------------|
| `store_put` | Write to SQLite store |
| `store_get` | Read from SQLite store |
| `store_list` | List atoms in a collection |
| `store_search` | Full-text search in a collection |
| `store_delete` | Delete an atom |
| `store_search_all` | Search across all collections |
| `knowledge_ingest` | Add to Postgres knowledge base |
| `knowledge_search` | Search Postgres knowledge base |
| `task_submit` | Submit task to Kart queue |
| `task_status` | Check task status |
| `task_list` | List pending tasks |

Every tool requires an `app_id` param. Authorization is checked via [SAP/1.0](https://github.com/rudi193-cmd/sap-rfc).

## OpenClaw config

```json
{
  "mcp": {
    "servers": {
      "willow": {
        "command": "python3",
        "args": ["-m", "willow_mcp"],
        "env": {
          "WILLOW_PG_DB": "willow",
          "SAP_SAFE_ROOT": "~/.sap/Applications",
          "SAP_PGP_FINGERPRINT": "YOUR_KEY_FINGERPRINT"
        }
      }
    }
  }
}
```

## Configuration

| Env var | Default | Description |
|---------|---------|-------------|
| `WILLOW_PG_DB` | `willow` | Postgres database name |
| `WILLOW_PG_USER` | `$USER` | Postgres user (Unix socket auth) |
| `WILLOW_STORE_ROOT` | `~/.willow/store` | SQLite store directory |
| `SAP_SAFE_ROOT` | `~/.sap/Applications` | SAFE folder root |
| `SAP_PGP_FINGERPRINT` | *(empty)* | Pinned GPG fingerprint |

## Authorization

Uses [openclaw-sap-gate](https://github.com/rudi193-cmd/openclaw-sap-gate) (SAP/1.0). Set up a SAFE folder for each app_id:

```bash
sap-gate init my-app
# edit ~/.sap/Applications/my-app/safe-app-manifest.json
# sign it, then:
sap-gate verify my-app
```

## License

MIT — Sean Campbell 2026
