---
name: gaps
description: Fleet gap backlog — log unknowns, resolve bookkeeping, promote verified answers into the KB
---

@markdownai v1.0

# /gaps — Gap backlog

Use when something is **unknown or contested** and should be tracked until a
verified answer lands in the knowledge base.

## Tools

| Tool | Permission | What it does |
|------|------------|--------------|
| `gap_log` | `gap_write` | Log or bump a topic+question (`asked_count` rises on repeat) |
| `gap_list` | `gap_read` | List gaps, most-asked first |
| `gap_resolve` | `gap_write` | Mark worked/answered — **SOIL bookkeeping only** |
| `gap_promote` | `gap_promote` | Land a verified answer into Postgres KB + close the gap |
| `gap_delete` / `gap_purge_topic` | `gap_write` / `gap_purge` | Soft-delete junk (archive, not hard delete) |

`gap_log` / `gap_list` / `gap_resolve` work **SOIL-only** (no Postgres).  
`gap_promote` needs Postgres and the same **schema-confirmation gate** as
`knowledge_ingest` — unconfirmed `knowledge` mapping → `unconfirmed_schema`.

## Promote workflow

1. `gap_list(status="open")` — pick `gap_id`, read `asked_count` for priority.
2. Gather sources and a human or agent identity for `confirmed_by`.
3. `gap_promote(gap_id=…, answer=…, sources=[…], confirmed_by=…)` — requires
   `gap_promote` permission (not included in everyday `gap_write`).
4. Gap status becomes `promoted`; atom is searchable via `knowledge_search`.

`gap_resolve` alone does **not** write KB — use it when work is in flight but
not yet promotable.

## Orchestrator seat (`app_id=willow`)

The human-orchestrator seat is **denied** `gap_*` tools by design (B-36): the
fleet backlog in SOIL still lives under `WILLOW_HOME`, but the orchestrator ACL
does not carry gap verbs. Participant agents with `gap_read` / `gap_write` /
`gap_promote` record gaps for this repo; fleet-wide governance stays in FRANK/KB.

## Constraints

@constraint severity=critical
Never call `gap_promote` without `sources` and `confirmed_by`. Never treat `gap_resolve` as landing knowledge — only `gap_promote` writes the KB. Do not widen the orchestrator group to fix B-36; use a participant `app_id` with gap permissions.
