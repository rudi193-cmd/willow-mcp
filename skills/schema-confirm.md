---
name: schema-confirm
description: Guided review and confirmation of a willow-mcp table's schema mapping before unlocking write tools for it
---

@markdownai v1.0

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

**1. Preview the mapping with a rendered sample row — do not confirm yet.**

Call `schema_confirm_mapping(table=..., preview=True)`. This returns the
proposed mapping **and** a `sample` — up to a few real rows projected through
that mapping, showing what each canonical field *actually* resolves to. It
writes nothing. Read the `sample` before anything else: a name match is an
assertion, not evidence, and the sample is the evidence.

> **Why this step is not optional.** On a real host schema, a `content` column
> can hold a *provenance blob* (tags, keywords, source ids) while the actual
> knowledge lives in `title`/`summary`. The heuristic maps `content → content`
> by name and looks correct; the `sample` is the only thing that shows the
> mapped `content` is metadata, not knowledge. Confirming on the name alone
> ships a mapping whose reads return the wrong column.

**2. Show the guesses field by field, against the sample.**

For each canonical field, state what the heuristic found **and what its sample
value actually looks like**:

- `exact` — the real column has the same name as the canonical field. Still
  check the sample value: an exact *name* match can be a wrong *content* match.
- `alias` — matched via the built-in alias list (e.g. `source_type` →
  `source`). State the real column name explicitly so the human can verify
  it's the right one, not just a plausible-sounding one.
- `unmapped` — no real column found. State this plainly; don't imply a
  fallback exists.

If a field's sample value is clearly the wrong data (metadata where you expected
content, an id where you expected text), that's an override to correct in
step 4, not a mapping to accept.

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

@constraint severity=critical
It will not call `schema_confirm_mapping` with no human input just to clear
an `unconfirmed_schema` error and move on. Confirming a mapping grants
standing to write against a real database using willow-mcp's understanding
of what its columns mean — per `docs/design/schema-adaptation.md` §3.4/§8,
that's a more consequential act than a single write, gated
(`schema_admin`) more strictly for exactly that reason. If asked to "just
make the error go away," explain why that's the wrong move here instead of
doing it.
