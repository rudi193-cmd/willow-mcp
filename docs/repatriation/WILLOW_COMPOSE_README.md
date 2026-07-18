# willow-compose

*The queryable memory of the Willow constellation — the code, the human, and the
collaboration, assembled into one and re-buildable from source. A sovereign piece the
hub calls, never contains.*

Assembled 2026-07-18 ("The Assembling"). Private by intent — this is a self-portrait.

---

## What this is

Three corpora, braided along seven `threads`, held in Postgres `willow_compose`:

- **`pieces`** (29,432) — *what was built.* Every function/method across the corpus,
  indexed via codebase-memory-mcp, deduped by MinHash, embedded (768-dim).
- **`voices`** (76) — *why.* The essays, the values, the human story.
- **`collaboration`** (42) — *how it felt.* The sessions, the mutual witness.
- plus `threads` (7), `toolkit` (281), `component_clusters` (307), `holdings` (25),
  `questions` (23, all answered), `gaps`.

This is **not** an operational service. It runs nothing. It is a *reflective layer* —
you query it when you want to ask the whole constellation a question. It sits parallel to
`willow_19` (the live-session memory) but for the code+human+collaboration corpus.

## Layout

```
engine/                  the re-runnable pipeline that builds everything
  process_repo.sh          clone → cbm index → extract → delete (disk-safe ingest)
  extract_pieces.py        cbm → willow_compose.pieces
  cluster_similar.py       MinHash near-dup clustering
  embed_pieces.py          local CPU embeddings (sentence-transformers, all-mpnet)
  decision_matrix.py       the consolidation matrix
  enact_axis*.py           the enact-axis (does a piece actually run?)
  triage_multilive.py      fork-family triage
  voices_seed*.py          the human leg
  collab_seed*.py          the collaboration leg
  threads_seed.py          the braid
  questions_seed.py        the 23 questions
docs/                    the meaning — THE_BOOK_OF_WILLOW, the handoffs, the inventories
willow_compose.dump      the data + vectors (pg_dump -Fc; see "the data" below)
```

## Restore (data → live)

```bash
createdb willow_compose
pg_restore -U <user> -d willow_compose willow_compose.dump
# pgvector 0.6.0 required for the embedding columns
```

## Rebuild (source → data)

The engine rebuilds the whole apparatus in one pass; see `engine/`. Ingestion is
disk-safe (clone → index → extract → delete), so the corpus never needs to fit on disk
at once. Embeddings regenerate on CPU via `engine/embed_pieces.py` (~1 hour for 29k
pieces on 4 cores).

## The data (and the 100 MB wall)

`willow_compose.dump` is ~123 MB — the bulk is 29,432 × 768 float embeddings. That is
over GitHub's 100 MB per-file limit for normal git. Three ways to carry it:

1. **git-lfs** (recommended) — `git lfs track "*.dump"`; the data travels with the repo.
2. **structure-only dump in git + regenerate** — a no-embedding dump is ~12 MB and fits
   git directly; `engine/embed_pieces.py` rebuilds the vectors (~1 hr CPU).
3. **release asset** — attach the full dump to a GitHub Release (2 GB limit).

## Relationship to the hub

`willow-mcp` stays lean. It **calls** willow-compose to ask the corpus a question; it does
not contain it. This is the ecosystem principle — sovereign pieces, called not absorbed —
applied to the constellation's own memory.

## What is deliberately NOT here

The private layer. Family specifics, medical, legal, schedules, names — surfaced during
the assembly, kept out of every durable artifact on purpose. The family-data apps
themselves live sovereign and local, outside this corpus by design. You protect the spec
by refusing to expose it.

*Plant the tree. Tend the roots. Name the ones you love. Let nothing be lost.*

*· ΔΣ=42*
