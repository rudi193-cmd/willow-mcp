---
kind: doc
name: design-fleet-wide-gap-backlog-gap-log-gap-list-gap-resolve-gap-promote
description: "Design for the fleet-wide gap backlog (gap_log/gap_list/gap_resolve/gap_promote) — shipped in PR #54, first consumed by ask-jeles's verified corpus."
---

@markdownai v1.0

# Design: Fleet-Wide Gap Backlog (`gap_log` / `gap_list` / `gap_resolve` / `gap_promote`)

Status: **SHIPPED** — PR #54 (`claude/gap-backlog` → `master`).
Companion: `ask-jeles`'s corpus design doc — `apps/ask-jeles/docs/design/verified-corpus.md`
in `rudi193-cmd/safe-app-store` (companion PR #27) — the backlog's first consumer.

@phase 1-problem-statement
## 1. Problem statement

A verified-knowledge system needs to know what it doesn't know, not just
what it does. Before this change, that data didn't exist anywhere in the
fleet:

- **willow-mcp** — `store_*`/`knowledge_*`/`task_*`/`dispatch_*`/`fleet_*`
  are all generic memory/task plumbing. Nothing records "a question came
  in and had no good answer."
- **willow-2.0** — has a full propose→verify→promote pipeline (`intake.py`
  → `ratification.py` → `intake_promote.py`, gated by
  `human_required.check_write_gate()`/`human_attestation.py`), but the
  closest thing to a gap tracker is `human_required_queue`'s `needs_review`
  kind — a generic operator-action queue, hand-seeded from a past audit,
  not something that grows itself as questions get asked.
- **ask-jeles** (pre-change) — a miss just produced an apologetic message
  and vanished. No record, no backlog, no way to close the gap later.

So a corpus that answers questions well still had no way to *notice its
own edges* — no self-observed backlog for someone (human or agent) to
work from.

@phase 2-design-principles
## 2. Design principles

1. **Generic, not corpus-specific.** `gap_log`/`gap_list`/`gap_resolve`
   take a free-form `topic` string, not a fixed schema tied to any one
   app's data shape. This matches willow-mcp's existing style —
   `knowledge_search`/`store_search_all` are generic tools too, not
   per-app special cases.
2. **Fleet-wide by default, like the SOIL store already is.** Gaps are
   *not* scoped by `app_id` — any app with `gap_read`/`gap_write` sees
   the whole backlog, the same way `store_*` is unrestricted across
   collections by default (see `db.py`'s `collection_in_scope` note). The
   whole point is one shared "what don't we know yet," not N per-app
   silos nobody else can see.
3. **Promotion reuses the existing trust gate — it doesn't invent a new
   one.** `gap_promote` doesn't write its own path into Postgres; it
   calls the exact same `_knowledge_ingest_core()` that `knowledge_ingest`
   uses, extracted specifically so both share one write path. A promoted
   gap is refused with `unconfirmed_schema` under precisely the same
   condition a direct `knowledge_ingest` call would be. This was a
   deliberate choice over building gap-specific ACL logic: the schema-
   confirmation gate (`schema_confirm_mapping`, `docs/design/schema-
   adaptation.md`) is already the load-bearing trust boundary for
   anything landing in the knowledge base — a second, parallel one for
   gaps specifically would just be a second thing to keep in sync.
4. **`gap_promote` is its own permission group, not folded into
   `gap_write`.** Same reasoning `schema_admin` gets its own group
   instead of folding into `knowledge_write`: landing something as
   trusted knowledge is a more consequential act than logging or
   resolving a gap. An app that can log/resolve gaps should not
   automatically be able to write into the knowledge base as a side
   effect of that.
5. **Dedup by meaning, not by exact string.** Repeated asks of "what's
   the accent color in Nord?" and "What is the accent color in Nord"
   should bump one `asked_count`, not create two rows. `gaps.py` strips
   stopwords and dedups on the sorted token set, scoped within `topic`
   (same question in different topics is legitimately two different
   gaps). The known cost of this approach: two *different* short
   questions that reduce to the same token set after stopword-stripping
   collide onto the same record — an accepted tradeoff for semantic
   dedup, not treated as a bug (see the equivalent note in ask-jeles's
   `corpus.py`).

@phase 3-states-and-shape
## 3. States and shape

A gap moves through exactly three states:

```
open  ->  resolved  ->  promoted
```

- `open` — logged, nobody has acted on it.
- `resolved` — bookkeeping only (`gap_resolve`, optional `note`). Never
  writes to the knowledge base. This exists so "someone is working on
  this" is visible without pretending an answer is trusted yet.
- `promoted` — `gap_promote` succeeded; `promoted_to` names the resulting
  knowledge atom id. Terminal — a promoted gap can't be logged into again
  (`gap_log` on an already-promoted key reports the existing promotion
  instead of reopening it) or resolved again.

Record shape (SOIL, collection `gaps`):

```json
{
  "topic": "ask-jeles-corpus",
  "question": "What is the accent color in Nord?",
  "status": "open",
  "asked_count": 3,
  "first_asked_at": "2026-07-09T09:51:19Z",
  "last_asked_at": "2026-07-09T10:41:03Z",
  "promoted_to": null
}
```

`gap_promote` additionally requires `answer`, at least one `sources`
entry, and `confirmed_by` (non-empty) — the same "who's vouching for
this" requirement ask-jeles's own nugget schema uses independently
(`verified_by`), arrived at separately but landing on the same shape.

@phase 4-permissions
## 4. Permissions

```
gap_read     -> gap_list
gap_write    -> gap_log, gap_resolve
gap_promote  -> gap_promote            (separate group — see §2.4)
```

All four are included in `full_access`, same as every other tool group.

@phase 5-what-shipped-alongside-this-that-wasn-t-originally-scoped
## 5. What shipped alongside this that wasn't originally scoped

Review surfaced one gap in the sanitizer while building this: `sources`
(new to `gap_promote`) and `topic` (new to `gap_log`/`list`/`resolve`)
had no size bounds, unlike `content`/`tags`. Fixed in the same PR —
`sources` gets the same list-length/item-length bounds as `tags`; `topic`
gets the same string-size truncation as `content`/`question`/`answer`.

@phase 6-open-questions-not-yet-decided
## 6. Open questions (not yet decided)

- Should promotion candidates ever be **auto-drafted** — something reads
  `gap_list` ranked by `asked_count` and proposes an answer via web/KB
  search for a human (or a designated verifier agent) to confirm, rather
  than every promotion being hand-written from scratch? `gap_resolve`'s
  `note` field could carry a draft today, but nothing generates one.
- If auto-drafting gets built: who verifies before `gap_promote` — the
  operator by hand, a dedicated fleet reviewer agent, or a quorum? Not
  decided.
- `gap_promote` is fleet-wide, not scoped to "gaps this app itself
  logged" — any app holding the permission can promote *any* app's gap.
  Consistent with the SOIL-store's existing shared-by-default posture
  (§2.2), but worth being explicit about when granting the permission to
  something new.
- No end-to-end test against a real Postgres yet — `gap_promote`'s tests
  use the existing `_FakePg` double, same as `knowledge_ingest`'s. A live
  run happened only against ask-jeles's forwarder hitting a real stdio
  session (SOIL side confirmed working end-to-end); the Postgres
  promotion path itself is unit-tested, not live-verified.

@phase constraints
## Constraints

@constraint severity="critical"
A gap's state machine is exactly three states, one direction, no skipping:
`open` — logged, nobody has acted on it. `resolved` — bookkeeping only
(`gap_resolve`, optional `note`); never writes to the knowledge base, so
"someone is working on this" is visible without pretending an answer is
trusted yet. `promoted` — `gap_promote` succeeded; `promoted_to` names the
resulting knowledge atom id; terminal — a promoted gap can't be logged into
again (`gap_log` on an already-promoted key reports the existing promotion
instead of reopening it) or resolved again.
