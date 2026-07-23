# The mai-conversion learning loop

Converting the fleet's documents to proper mai (per
[`markdownai-schema.md`](markdownai-schema.md)) is run as a **learning loop**,
not a one-shot swarm: small bites, each one feeding the next.

```
        ┌─────────────────────────────────────────────────────┐
        │  1. pick the next bite (smallest coherent doc set)    │
        │  2. read accumulated learnings from the KB            │←──┐
        │     (knowledge_search source="mai-conversion-loop")  │   │
        │  3. dispatch a Sonnet agent, PRIMED with the learnings│   │
        │  4. agent converts + validates + reports NEW gaps     │   │
        │  5. live-verify via the mai tools; fix real issues    │   │
        │  6. persist new learnings → KB;  update SOIL loop-state│──┘
        │  7. commit the bite.  loop until no docs & no new gaps │
        └─────────────────────────────────────────────────────┘
```

The loop gets *loopier* each round: step 2 means bite N+1 starts from
everything bites 1..N learned, so the gap list shrinks toward zero (loop-until-
dry — the same shape as the sandbox's stupid-tests harness).

## Memory

- **Learnings** → KB atoms, `source="mai-conversion-loop"`, domain `saps1`.
  The canonical, growing playbook. Retrieve before every bite.
- **Loop state** → SOIL record `saps1/mai-loop-state` (bites done, next bite,
  exclusions, learning-atom ids). Updated in place each round.

## Scope

In: `safe-app-store`, `willow-mcp`, `utety`, `oakenscrolls-office`.
Out (never stamped): **willow-2.0** (the reference), **codebase-memory-mcp**
(third-party DeusData fork), `LICENSE`, `vendored/`, `node_modules/`,
generated files.

## Accumulated learnings (regenerated from the KB)

1. **Quote placeholder frontmatter values** — `title: "{title}"`, not
   `title: {title}` (unquoted `{…}` is a YAML flow mapping and breaks).
2. **Enum fields take a default, not a placeholder** — `priority: normal` in
   frontmatter; keep the `{high | normal | low}` hint in the body.
3. **`@db` needs `on-error`** when the table may not exist. Findings live in
   `handoff.json`, not a Postgres `findings` table — a bare `@db` renders a raw
   SQL error into the doc.
4. **`@constraint` captures greedily** to the next `@constraint`/EOF — place
   last or group them. Close every `@macro`/`@prompt`/`@if` block.
5. **`@db` attr values can't contain `|` or unescaped `"`** — so double-quoted
   SQL column aliases don't fit inside `raw="…"`; headers use raw column names.
6. **Keep template copies in sync** — `docs/templates/` and
   `src/willow_mcp/bundle/templates/` must stay byte-identical.

## Bite ledger

| # | Bite | Status | Gaps found |
|---|------|--------|-----------|
| 1 | willow-mcp templates (ASSIGNMENT, CLOSEOUT ×2 copies) | committed | 6 (folded in above) |
| 2 | willow-mcp skills (13) — #154 | dispatched | — |
