# Design: Schema Adaptation for Host Databases

Status: DRAFT — not yet implemented or ratified.
Author: Ada (fleet id: willow), 2026-07-08, following operator design conversation.
Motivating incident: PR #3 smoke test — `knowledge_search`, `kb_startup_continuity`,
and `kb_at` crashed with `UndefinedColumn: "source"` against a real production
`knowledge` table; `fleet_health` crashed with `UndefinedTable: "kart_task_queue"`.
Root cause: `server.py` hardcodes column/table names for tables it does not own
and never created. `fleet_status` succeeded in the same test, because it happened
to match the real `agents` table by coincidence — proving the tool *can* usefully
read a live host schema when the assumption is right, and crashes hard when it
isn't. See conversation log for the full reasoning trail.

## 1. Problem statement

willow-mcp is meant to be pointed at **someone else's** database, not its own.
The operator gave three concrete tiers of "someone else":

1. **A builder with scattered DBs/KBs** — several personal projects, each with
   a knowledge or task table that evolved independently. Schemas are similar
   in spirit, diverged in detail (`source` vs `source_type` vs `origin_ref`).
2. **A mid-size office with decades of databases** — provenance is unclear,
   nobody currently on staff necessarily knows what a given table means or
   who last touched it. Some tables may be load-bearing for processes nobody
   has documented.
3. **A DOD contractor, or DOD itself** — the stakes tier. Wrong writes are not
   an inconvenience, they are potentially a compliance or safety incident.
   Every read and write needs to be defensible after the fact.

Across all three, the common shape is the same: **willow-mcp does not get to
assume it knows what a table means.** It has to find out, say what it found,
and treat writing into an inference as a categorically different — and much
more dangerous — action than reading from one.

This rules out both options considered earlier in the conversation:

- **Self-provisioned isolated schema** (`willow_mcp.*` namespace, own tables) —
  wrong, because then the tool never actually engages with the host's real
  data. It solves the crash but defeats the entire premise of "works with any
  codebase."
- **Hardcoded column names** (today's code) — wrong, demonstrably: it crashes
  the instant the host schema doesn't match the author's assumption, and by
  tier 2 above, nobody may be positioned to notice it silently returned
  wrong data instead of crashing.

## 2. Design principles

1. **Discover, don't assume.** Before any tool issues SQL against a host
   table, it queries `information_schema` for that table's real columns and
   types. No query string embeds a column name that wasn't confirmed to
   exist in *this* database, *this* run.
2. **Map to canonical concepts, with visible confidence.** willow-mcp's tools
   speak in canonical fields (`id`, `content`, `domain`, `source`, `tags`,
   `created_at`, …). A per-database **mapping** translates canonical fields to
   whatever the host schema actually calls them, using name/type heuristics
   (aliases, substring match, type compatibility). Every mapped field carries
   a confidence tier (`exact` / `alias` / `inferred` / `unmapped`) — this is
   surfaced to the caller, never hidden.
3. **Reads may infer. Writes may not guess.** A read using an `inferred`
   mapping degrades gracefully — missing fields come back `null` or omitted,
   annotated with which mapping tier produced them, rather than raising. A
   write is refused unless the target column's mapping has been explicitly
   confirmed (see §4) for that specific table in that specific database.
   This is the load-bearing safety rule for tiers 2 and 3 above.
4. **The mapping is an artifact, not a black box.** Once computed, a mapping
   is written to a reviewable, editable file (see §5) — not held only in
   memory, not silently re-guessed differently on the next run. A human (or
   an audit process) can read exactly what willow-mcp believes a table's
   columns mean, correct it, and have the correction persist and take
   precedence over the heuristic from then on.
5. **Every inference is logged.** Which columns were discovered, what they
   were mapped to, at what confidence, and — critically — what mapping was
   *in effect* at the time of any write. This is the same tamper-evident
   posture as the fleet's own FRANK ledger: the log is what makes an
   inference defensible after the fact, which matters most exactly in tier 3.

## 3. Architecture sketch

```
                 ┌─────────────────────┐
   tool call ───▶│  canonical query     │   e.g. knowledge_search(app_id, query)
                 │  (server.py)         │
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  SchemaProfile       │   per (db, table) — cached, file-backed
                 │  .resolve(table)     │
                 └──────────┬───────────┘
                            │  cache miss / stale?
                            ▼
                 ┌─────────────────────┐
                 │  introspect()        │   information_schema.columns
                 │  + propose_mapping() │   canonical → real column, w/ confidence
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  mapping artifact    │   $WILLOW_HOME/mcp_apps/<app_id>/
                 │  (reviewable JSON)   │   schema_maps/<db_fingerprint>.json
                 └──────────┬───────────┘
                            ▼
                 ┌─────────────────────┐
                 │  query builder       │   builds SQL only from confirmed-
                 │  (read vs write path)│   present columns; write path checks
                 └──────────┬───────────┘   mapping.confirmed before allowing
                            ▼
                     SQL against host DB
```

### 3.1 `SchemaProfile`

A small module (`schema_profile.py`) responsible for:

- `introspect(conn, table) -> list[ColumnInfo]` — one `information_schema`
  query per table, cached in-process per connection lifetime.
- `propose_mapping(columns, canonical_fields) -> Mapping` — heuristic pass:
  exact name match → known aliases (`source_type`, `origin`, `origin_ref` →
  `source`; `body`, `text` → `content`; …) → type-compatible best-effort guess
  → unmapped. Each field in the returned `Mapping` carries `{column, tier,
  confidence}` or `None` if nothing plausible was found.
- `load_confirmed(app_id, db_fingerprint, table) -> Mapping | None` — reads a
  previously-saved, human-reviewed mapping if one exists; this always wins
  over a fresh heuristic guess.
- `db_fingerprint(conn)` — stable identifier for "this database" (e.g. hash
  of host + dbname, not connection-string secrets) used as the mapping
  artifact's key, so the same database is recognized across restarts even if
  reached via a different app_id.

### 3.2 Mapping artifact

Stored at `$WILLOW_HOME/mcp_apps/<app_id>/schema_maps/<db_fingerprint>__<table>.json`:

```json
{
  "database": "postgres://host/dbname",
  "table": "knowledge",
  "discovered_at": "2026-07-08T03:40:00Z",
  "confirmed": false,
  "fields": {
    "id":         {"column": "id",          "tier": "exact"},
    "content":    {"column": "content",     "tier": "exact"},
    "domain":     {"column": "domain",      "tier": "exact"},
    "source":     {"column": "source_type", "tier": "alias", "confidence": 0.9},
    "tags":       {"column": null,          "tier": "unmapped"}
  }
}
```

`confirmed` starts `false` (heuristic only). A human — or an explicit
`schema_confirm_mapping` tool call gated the same way `knowledge_ingest` is
gated today — flips it to `true`, optionally editing individual field
mappings first. Only `confirmed: true` mappings unlock write tools for that
table. This file is plain JSON specifically so it's diffable, greppable, and
reviewable without a special tool — an auditor in tier 3 can read it cold.

### 3.3 Read path

`knowledge_search`, `kb_at`, `kb_startup_continuity`, `fleet_health`, etc.
build their `SELECT` column list from `mapping` at call time, using whatever
real column names were discovered — `exact`, `alias`, or `inferred` tiers all
participate in reads. A canonical field with `tier: unmapped` is simply
omitted from the result (or returned as `null` with a `"_unmapped": [...]`
marker) rather than raising `UndefinedColumn`. This directly fixes today's
crash: `source` unmapped or aliased to `source_type` never produces bad SQL.

### 3.4 Write path

`knowledge_ingest`, `kb_promote`, `kb_journal`, and any future write tool
check, per targeted column, that the mapping for that field is `confirmed:
true`. If not:

```json
{"error": "unconfirmed_schema: field 'source' on table 'knowledge' has not "
          "been confirmed for this database — call schema_confirm_mapping "
          "or edit the mapping file directly, then retry"}
```

No silent best-effort writes, ever. This is the tier-2/tier-3 safety
boundary: reads can be helpful-and-approximate, writes must be
correct-or-refused.

### 3.5 Relationship to `gate.py`

`gate.py`'s manifest ACL answers "may this `app_id` call this *tool*."
Schema confirmation answers a narrower question underneath that: "may this
*write* proceed against this *table*, in *this* database, given what we
currently believe its columns mean." Both checks apply — a caller can be
permitted the `knowledge_write` group and still be refused a specific write
because the mapping for that host table isn't confirmed yet. These are
independent, composable gates, not a replacement for one another.

## 4. Degradation & error behavior

- Table introspection fails entirely (no such table) → tool returns
  `{"error": "table_not_found: <table>"}`, no exception surfaces to the
  transport.
- Table exists, canonical field unmapped → read omits/nulls that field,
  annotates `_unmapped`; write touching that field is refused per §3.4.
- Mapping file present but stale (host schema has since changed columns) →
  re-introspect, diff against the saved mapping, and if the *confirmed*
  mapping's columns no longer exist, downgrade `confirmed` to `false` and
  surface a `schema_drift` warning rather than writing against columns that
  may no longer mean what a human confirmed them to mean.

## 5. Audit logging

Every introspection, every mapping proposal, every confirmation, and every
write's *effective mapping at time of write* gets an entry in a local
append-only log (candidate: reuse the existing FRANK ledger pattern from
willow-2.0, or a lighter per-app JSONL under `$WILLOW_HOME/mcp_apps/<app_id>/
schema_audit.jsonl` if willow-mcp shouldn't depend on FRANK directly for a
public-facing package). Minimum fields: timestamp, app_id, table, mapping
snapshot, tool called, confirmed-by (human/heuristic).

## 6. Open questions (for next pass, not blocking the write-up)

- **Aliasing dictionary scope.** Should common aliases (`source`/`source_type`/
  `origin`) ship as a static built-in list, or be per-deployment configurable?
  Static-but-extensible seems right; a config override file is cheap to add.
- **Who can call `schema_confirm_mapping`?** Presumably gated at least as
  strictly as `knowledge_write` — arguably its own permission group, since
  confirming a mapping is a more consequential act than a single write.
- **Cross-database identity for `db_fingerprint`.** Needs to be careful not
  to leak connection secrets into a mapping filename or content, while still
  being stable enough to recognize "the same database" across restarts.
- **SQLite `Store` tools are unaffected** — they already own their schema
  (`records` table, created by `Store.__init__`), so none of this applies to
  `store_*`. This design is scoped to the Postgres-backed tools only
  (`knowledge_*`, `kb_*`, `task_*`, `agent_*`, `fleet_*`).
- **Performance** — introspection + mapping resolution should be cached per
  connection/process lifetime (not re-queried per call), invalidated only on
  detected schema drift (§4) or explicit cache-bust.

## 7. Rollout shape (sketch, not committed)

1. `schema_profile.py` — introspection + heuristic mapping + artifact
   read/write, unit-tested against a handful of synthetic schemas (matching
   column, aliased column, missing column, extra columns).
2. Wire read tools (`knowledge_search`, `kb_at`, `kb_startup_continuity`,
   `fleet_health`) through the mapping instead of hardcoded SQL — this alone
   fixes today's crash and is safe to ship independently.
3. Add `schema_confirm_mapping` tool + write-path gate for
   `knowledge_ingest` / `kb_journal` / `kb_promote`.
4. Add audit logging.
5. Only after the above: revisit `task_*`/`agent_*` tools, which currently
   assume a `kart_task_queue` / `routing_decisions` shape that may not exist
   at all in a host database — same introspect-or-refuse treatment, plus a
   decision on whether willow-mcp should be allowed to *create* a task queue
   table when none exists (a write-time question, not a read-time one, and
   arguably its own consent gate distinct from schema confirmation).
