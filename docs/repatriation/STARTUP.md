# STARTUP — box holdings map (cold-session continuity)

Query live: `psql -U root -d willow_compose -c 'SELECT kind,name,scope,size,location FROM holdings ORDER BY kind,name'`

| kind | name | scope | size | access |
|---|---|---|---|---|
| service | postgresql-16 | infra | 2.2G | psql -U root |
| service | willow-mcp | live |  | mcp__willow-mcp__* tools |
| service | codebase-memory-mcp | tool | 254M | cbm cli <tool> | MCP |
| service | willow-2.0-sap_mcp | dormant | 308M | mcpdrive stdio |
| service | grove | offline |  | OAuth (unavailable) |
| postgres | willow_19 | live | 1279 MB | psql -U root -d willow_19 |
| postgres | willow_compose | analysis | 69 MB | psql -d willow_compose |
| postgres | willow | sandbox | 8175 kB | psql -d willow |
| postgres | willow_vault | snapshot | 7767 kB | psql -d willow_vault |
| postgres | willow_vault_jul16 | snapshot | 7767 kB | psql |
| postgres | willow_ci | test | 7735 kB | psql |
| postgres | corpuslens_test | test |  | psql |
| soil | willow-live-store | live | 892K | via willow-mcp server (WILLOW_STORE_ROOT) |
| soil | willow-mcp-sandbox-store | sandbox | 312K | store_* MCP tools |
| soil | vault-restore | snapshot | 944M | filesystem |
| kb | willow_19.knowledge | live | 1279 MB | knowledge_search / kb_at |
| kb | willow_19.opus_atoms | live | 1279 MB | psql |
| kb | willow_compose.pieces | analysis | 69 MB | psql / engine scripts |
| cbm | code-graph-cache | tool | 126M | cbm cli query_graph/search_graph |
| ledger | frank-receipts | live |  | frank_* MCP / receipts_tail |
| vault | local-vault | live | 12K | encrypted vault |
| toolkit | willow-toolkit | analysis | 3.5M | filesystem |
| table | component_clusters | analysis |  | psql |
| table | toolkit | analysis |  | psql |
| repos | source-clones | source |  | git |

## Load-bearing (don't lose)
- **willow_19** (Postgres) — production KB, ~229k atoms. Live server writes here.
- **/workspace/willow-live/store** — live SOIL, 107 collections.
- **willow_compose** — this analysis (pieces/clusters/toolkit/holdings).

## Gotcha
Shell env → sandbox (`willow` db, `.willow/store`). The running server → live (`willow_19`, `willow-live/store`). Raw psql hits the sandbox.