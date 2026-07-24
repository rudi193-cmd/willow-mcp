# Willow tool roll — scripts

Preserved as-run from session `evening-chat-i5i6tr` (2026-07-24). These are the
tools the manual's workshop chapter **Tools for the job** describes — persisted
here so the chapter points at something real instead of a `/workspace` that gets
reclaimed.

**Snapshot, not turnkey.** Each script hardcodes `/workspace` paths and specific
DB names (`willow_19`, `willow_0723`, `willow_both`, `willow_vault`) and vault
store paths. Read the header and hoist the roots before reuse — they're the
record of what actually worked, a runbook to adapt, not a finished CLI.
Deliberately excluded: the self-grant "grinder" and the one-off exploration junk.

Mirrors: `willow-tech-manual` → `docs/workshop/01-tools-for-the-job.md`.

## `reconstruction/` — the bench roll (rebuild the KB from the vault)

Canonical long-term home is `sean-data-vault/scripts/`, next to
`restore-and-wire.sh` (the half that script doesn't cover). Kept here too so
nothing is lost to reclaim.

| Script | Does |
|---|---|
| `load_willow19.sh` | Load the 229k-atom corpus dump → Postgres `willow_19` (pgvector, part-file concat, `\restrict` strip, `ON_ERROR_STOP=0`) |
| `load_0723.sh` | Load the 07-23 curated KB → `willow_0723`; report counts by domain |
| `complete_0723.sh` | Give `willow_0723` the full willow-mcp aux-table set (tasks/agents/routing_decisions + knowledge_edges) |
| `build_both.sh` | Build `willow_both`: the union VIEW folding curated (`k0723`) + corpus (`k19`) into canonical `id/content/domain/source/tags` — **the schema decision** |
| `fix_view.sh` | Rebuild the union VIEW to the canonical 5 columns only |
| `check_w19.sh` | Sanity: `willow_19` columns, row count, top domains |
| `inv.py` | Inventory every SQLite DB under a vault root (tables + row counts + KB-table detection) — era-spanning probe |
| `schema.py` | Dump the schema of legacy stores (windows-era `willow_knowledge.db`, `willow-2.0.db`, …) |

## `ratification/` — the ride roll (seal & verify)

| Script | Does |
|---|---|
| `dump_seals.py` | Pull `type=finding, verification_status=verified` records out of a SOIL `store.db` |
| `pick_finding.py` | List the verified findings in a SOIL store |
| `pick_and_check.py` | Pick a finding and cross-check it against the live `willow_both` KB |
| `verify_seal.sh` | Confirm one seal landed in the writable head (`k0723`), not stranded in the raw corpus |
| `verify_batch.sh` | Batch reconciliation counts + content spot-checks in `willow_both` |
| `snapshot_edge.py` | Date-stamp a lineage snapshot from the live SOIL store |

## `diagnostics/` — read-only "check the plug color"

| Script | Does |
|---|---|
| `kb_stats.sh` | Corpus totals + duplicate-title dedup magnitude on `willow_19` |
| `corpus_map.sh` | Corpus composition: top categories / projects / source_types |
| `soil_gaps.py` | Dump the SOIL gaps / research stores |
