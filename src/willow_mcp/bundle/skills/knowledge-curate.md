---
name: knowledge-curate
description: Flag or retract KB atoms in place via tags — knowledge_flag and knowledge_retract (#159)
---

@markdownai v1.0

# /knowledge-curate — KB flag and retract

Use when an atom is **wrong, synthetic, or stale** but should not be hard-deleted.
State lives in **`tags`** (`kb:flagged`, `kb:retracted`, JSON metadata).

## Permission

`knowledge_flag` and `knowledge_retract` require **`knowledge_curate`** — not in
`full_access` or `knowledge_write`. Grant explicitly (same separation as `gap_promote`).

Requires Postgres + confirmed `knowledge` mapping with a mapped **`tags`** column.

## Flag

```
knowledge_flag(atom_id=…, reason=…, severity=info|low|medium|high|critical, refs=[…])
```

Idempotent marker; `kb_at` surfaces `kb_flag`. Search/continuity still return the
atom unless retracted.

## Retract

```
knowledge_retract(atom_id=…, reason=…)
```

Sets `kb:retracted`. Default `knowledge_search` and `kb_startup_continuity` **hide**
retracted atoms; `kb_at` shows `retracted: true`.

Retraction is a tombstone — not a delete. Original content remains for audit.

## vs promote / ingest

| Action | Tool | Effect |
|--------|------|--------|
| Add trusted knowledge | `knowledge_ingest` / `gap_promote` | New or promoted atom |
| Mark suspect | `knowledge_flag` | Visible flag in tags |
| Hide from default search | `knowledge_retract` | Tombstone tag |

## Constraints

@constraint severity=critical
Do not retract instead of promoting a corrected atom when the fleet needs the replacement searchable — retract the bad row and ingest or `gap_promote` the fix. Flag severity must be one of the documented levels; do not use curate tools without `knowledge_curate` on the manifest.
