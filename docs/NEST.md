# The Nest — personal-file content pipeline

> *"Dump your life and let the pigeon figure it out."*

The Nest is a content pipeline for a folder of personal files. Point it at a
drop folder; it walks the tree, extracts text (OCR / PDF / docx / plaintext),
classifies each file's fragments **by meaning**, and writes a canonical SQLite
Nest DB. That DB — a person's legal filings, journals, receipts, messages — is
the **local PII zone**. From it, the Nest promotes *structure* (not content)
into the shared knowledge base.

The engine (`willow_mcp.nest`) is vendored from
[`rudi193-cmd/safe-app-store` `apps/nest-seed`](https://github.com/rudi193-cmd/safe-app-store)
(MIT). This first cut ships the **content pipeline** only; the live drop-folder
router (scan → human-gate → file-move) is a later step.

## The tools

All four are gated by the manifest ACL (`gate.py`): `nest_read` grants the
read tools, `nest_write` the writes. All run through `_guarded`, so egress
secret redaction and receipts apply to every result.

| Tool | Group | Does |
|------|-------|------|
| `nest_scan` | `nest_write` | Walk a folder → extract → classify → write a SQLite Nest DB. Returns counts. `dry_run=True` (default) reports without writing. |
| `nest_status` | `nest_read` | Sources by status, fragments by type, topical categories by size. |
| `nest_digest` | `nest_read` | A one-page Markdown map — the **walled** view. |
| `nest_promote` | `nest_write` | Promote the Nest's **structure** into the KB (`_knowledge_ingest_core`). `dry_run=True` returns the atoms that would be promoted. |

```
nest_scan  ──►  SQLite Nest DB  ──►  nest_status / nest_digest  (read it back)
 (drop folder)   (local PII zone)          │
                                            └─►  nest_promote  ──►  knowledge base
                                                 (structure only, walled)
```

Classification is a cheapest-tier-first cascade: **regex** facts → local
**embedding** centroids (Ollama `nomic-embed-text`) → a local **LLM** on the
uncertain tail (`--llm`). Every tier degrades gracefully when its model is
absent, falling back to regex. No cloud inference; nothing leaves the machine.

Optional source-type support (OCR / PDF / docx) installs with
`pip install willow-mcp[nest]` plus system `tesseract-ocr` and `poppler-utils`.
The base install stays dependency-free.

## The wall

The Nest DB holds raw content. The promotion path must not carry it into the
shared KB. The guarantee — the same seam corpus-lens's Guard enforces:

> **Relative/structural shape is process — shareable. Absolute content — a
> name, a date, a filename — is person — walled.**

Enforced mechanically, in three places:

1. **`nest_promote` can only reach `bridge.build_bridge`**, which selects
   **counts + curated category names + redacted secret *kinds*** — never a
   fragment's content. It is structurally incapable of ingesting content.
2. **A category allowlist.** A fragment's `label` is a real topical category
   only when the embedding/LLM tier classified it; the regex fallback labels a
   document/receipt with its **filename** (which embeds dates and names). Only
   allowlisted category names (`legal`, `journal`, `financial`, … or a curated
   `auto:` cluster) cross the wall — a filename never does. Dropped fragments
   are **counted as `uncategorised`**, honestly, not silently hidden.
   (`nest_status`, `nest_digest`, and `nest_promote` all apply this filter.)
3. **`nest_digest` returns the walled view over MCP.** Person names, the date
   timeline, and source filenames are suppressed; the full unwalled digest is a
   local-CLI affordance only.

Plus the standing `_guarded` backstop: every tool result is passed through
`secret_scan.redact_egress`, so a stray credential in any Nest output is
redacted and receipted before it leaves.

`tests/test_nest.py` holds the wall to these claims — including the load-bearing
`test_bridge_emits_no_content_names_or_filenames` and the
`test_bridge_drops_filename_labels` regression.

## What is out of scope (by design)

- **The live drop-folder router** (`willow-2.0` `nest_intake`): scan a desktop
  folder, stage a review queue, human confirm/override/skip, move the file, and
  learn from the correction. That workflow is the natural next step, not this cut.
- **Owner ≠ subject.** A life dump contains people who are not its owner — a
  co-parent, a child. The Nest classifies them into `person` fragments locally;
  the wall keeps those out of the shared KB, but the deeper consent question
  (may their data be here at all?) is unsolved here, as it is in corpus-lens.
