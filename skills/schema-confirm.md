---
name: schema-confirm
description: Guided review and confirmation of a willow-mcp table's schema mapping before unlocking write tools for it
---

# /schema-confirm

Walks through reviewing a willow-mcp table's schema mapping and confirming
it (`schema_confirm_mapping`) — the write-path gate described in
`docs/design/schema-adaptation.md` §3.4. Use this instead of calling
`schema_confirm_mapping` directly with hand-written overrides.

## When to use this

- A write tool (`knowledge_ingest`, `kb_journal`, `kb_promote`) returned
  `unconfirmed_schema`.
- A read tool's response included `"_unmapped": [...]` and you want fields
  currently unmapped to become writable.
- You're pointing willow-mcp at a new database for the first time.

## Steps

**1. Surface the current heuristic mapping, read-only.**

Call a read tool against the target table first — `knowledge_search` with
any query, or `kb_startup_continuity` — and look at its `_unmapped` field.
This reflects `schema_profile.resolve()`'s heuristic guess without writing
anything. Do not call `schema_confirm_mapping` yet.

**2. Show the guesses field by field.**

For each canonical field (`id`, `content`, `domain`, `source`, `tags` for
the `knowledge` table today), state what the heuristic found:

- `exact` — the real column has the same name as the canonical field. Low
  risk, usually fine to accept as-is.
- `alias` — matched via the built-in alias list (e.g. `source_type` →
  `source`). State the real column name explicitly so the human can verify
  it's the right one, not just a plausible-sounding one.
- `unmapped` — no real column found. State this plainly; don't imply a
  fallback exists.

**3. Ask for confirmation or correction, per field.**

For each field, ask: accept the guess, supply a different real column name,
or explicitly leave it unmapped (`null`). Do not assume silence means
accept — an unanswered field should stay whatever it already was rather
than being silently confirmed.

**4. Call `schema_confirm_mapping` once, with the accumulated overrides.**

```
schema_confirm_mapping(app_id=..., table="knowledge", overrides={
  "source": "origin_ref",   # human corrected the heuristic's guess
  "tags": null,              # human confirmed: genuinely not present, leave unmapped
})
```

Only include a field in `overrides` if the human corrected or explicitly
confirmed something different from the heuristic default — fields the
heuristic already got right don't need to be repeated.

**5. Report what's now unlocked.**

State which write tools are now usable for this table, and name any field
that's still `unmapped` — those fields will keep coming back `null` on
reads and can't be targeted by writes until a real column is found and the
table is re-confirmed.

## What this skill will not do

It will not call `schema_confirm_mapping` with no human input just to clear
an `unconfirmed_schema` error and move on. Confirming a mapping grants
standing to write against a real database using willow-mcp's understanding
of what its columns mean — per `docs/design/schema-adaptation.md` §3.4/§8,
that's a more consequential act than a single write, gated
(`schema_admin`) more strictly for exactly that reason. If asked to "just
make the error go away," explain why that's the wrong move here instead of
doing it.
