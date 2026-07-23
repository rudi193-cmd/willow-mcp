# Box inventory — data & services (2026-07-18)

Everything holding state in this session's container, and what runs.

> **Ephemeral:** this is a per-session container. Only what's committed/pushed or
> sent out survives reclamation. Nothing below is durable unless noted.

---

## 1. Services / servers running

| Service | How it runs | Notes |
|---|---|---|
| **PostgreSQL 16** | `/usr/lib/postgresql/16/bin/postgres -D /var/lib/postgresql/16/main` | **Unix socket only** (`/var/run/postgresql`), no TCP port exposed. User `root`. Serves all DBs below. pgvector 0.6.0 available. |
| **willow-mcp** (MCP) | `.venv/bin/python3 -m willow_mcp` (stdio, this session) | The live product server. Runs against `willow_19` + `/workspace/willow-live/store` (see §5 config split). |
| **codebase-memory-mcp** (MCP) | stdio, binary `codebase-memory-mcp` | Built this session at `/workspace/codebase-memory-mcp/build/c/`. Code-graph store in `/root/.cache/codebase-memory-mcp`. |
| **willow-2.0 sap_mcp** | not persistent | Stood up transiently for the drive-test; venv at `/workspace/willow-2.0/.venv2`. Not currently serving. |
| **Grove** (MCP) | configured, **needs auth** | Unavailable this session (OAuth not completed). |
| Ollama / local inference | **not running** | — |

Remote MCP connectors in scope (not on this box): GitHub, Gmail, Google Calendar/Drive, Grove.

---

## 2. PostgreSQL databases (8)

| DB | Size | Tables | Role |
|---|---:|---:|---|
| **willow_19** | **1279 MB** | 24 | **The production KB / fleet DB.** What the live willow-mcp server actually uses. |
| **willow_compose** | 69 MB | 3 | **This session's analysis DB** (the corpus work). |
| willow | 8.2 MB | 12 | Standalone willow-mcp schema (sandbox default; *not* what the server uses). |
| willow_vault | 7.6 MB | 3 | Vault snapshot (knowledge/tasks/edges). |
| willow_vault_jul16 | 7.6 MB | 3 | Older vault snapshot. |
| willow_ci | 7.6 MB | 4 | CI test DB. |
| corpuslens_test_809897e3 | 7.4 MB | — | corpus-lens test DB. |
| postgres | 7.5 MB | — | Cluster default. |

**`willow_19` contents (the crown jewel):**
- `knowledge` — **1207 MB (~229k atoms)** — the main knowledge base.
- `messages` 39 MB · `binder_edges` 12 MB · `opus_atoms` 9.8 MB (Opus-tier KB) · plus `tasks`, `agents`, `routing_decisions`, `session_index`, `run_events`.

**`willow_compose` contents (ours):** `pieces` 29,432 rows (60 MB) · `component_clusters` 307 · `toolkit` 281.

---

## 3. SOIL stores (SQLite key-value, per-collection)

| Path | Size | Collections | Role |
|---|---:|---:|---|
| **`/workspace/willow-live/store`** | 892 KB | **107** | The **live** SOIL store the running server writes (agents_*, gaps, handoffs, lineage, cube_cells, chunk_index…). |
| `/workspace/willow-live/vault-store` | — | — | Live vault SOIL store. |
| `/home/user/willow-mcp/.willow/store` | 312 KB | ~15 | Repo-local **sandbox** SOIL store (gitignored): gaps, lineage, notes, per_tool… |
| `/workspace/vault-restore/.willow/store` | (in 944 MB dir) | — | A **restored vault snapshot** + `inspect-home/`. |

---

## 4. Knowledge bases (summary)

- **Postgres `willow_19.knowledge`** — 1.2 GB, ~229k atoms — primary KB.
- **`willow_19.opus_atoms` / `binder_edges` / `messages`** — Opus-tier KB, binder graph, Grove message log.
- **`willow_compose.pieces`** — 29,432 code symbols w/ MinHash (our corpus KB).
- `.willow/knowledge/` — near-empty local dir.

---

## 5. Code-intelligence store (cbm)

- **`/root/.cache/codebase-memory-mcp`** — 126 MB, **8 project DBs** still present: willow-2.0, willow-mcp, kartikeya, willow-gate, corpus-lens, sean-data-vault, willow-data-vault, codebase-memory-mcp. (The other 28 indexed repos were `delete_project`'d by the disk-safe pipeline; re-index in ~seconds.)
- `…/scratchpad/w2home/code_graph.db` — leftover from the willow-2.0 drive-test.

---

## 6. Ledgers / receipts / vault (files under `.willow/`)

- `mcp_receipt.db` (48 KB) — tool-call receipts.
- `vault.db` + `vault.key` (12 KB) — encrypted local vault.
- `ledgers/`, `.kart-logs/`, `worker_heartbeat/` — FRANK/Kart logs & liveness.
- `mcp_apps/` (132 KB) — manifest ACLs + identity bindings.
- `schema_rings.json`, `config/`, `constitutional/`, `personas/`, `seeds/`.

---

## 7. Config split worth knowing

The shell env and the actual MCP server disagree on where "willow-mcp data" lives:

| | Shell env | Live MCP server (`.mcp.json`) |
|---|---|---|
| Postgres DB | `willow` (8 MB sandbox) | **`willow_19`** (1.28 GB production) |
| SOIL store | `.willow/store` (312 KB sandbox) | **`/workspace/willow-live/store`** (live) |
| app_id | `willow` | `operator` |

So a plain `psql`/shell action hits the **sandbox**; the running server reads/writes the **live** `willow_19` + `willow-live/store`.

---

## 8. Repo clones on disk (source; also hold state)

4.5 G `sean-data-vault` · 1.8 G `codebase-memory-mcp` · 466 M `willow` · 308 M `willow-2.0` · 108 M `willow-mcp` (`/home/user`) · then `willow-config`, `safe-app-willow-grove`, `kartikeya`, `aionic-claude-skills`, `corpus-lens`, `willow-gate`, `willow-data-vault`, `willow-bot` (all < 4 MB). ~17 G free.

---

## 9. This session's artifacts (scratch — ephemeral)

- Engine: `extract_pieces.py`, `cluster_similar.py`, `decision_matrix.py`, `tool_catalog.py`, `assemble_toolkit.py`, `materialize_toolkit.py`, `process_repo.sh`, `pieces.sql`.
- Outputs: `willow_compose.dump` (delivered), `CONSOLIDATION_MATRIX.md` (delivered), `willow-toolkit/` + `willow-toolkit.tar.gz` (delivered).
