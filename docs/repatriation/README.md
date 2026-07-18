# Repatriation — a session, left as a ring

This directory is the record of one large session (2026-07-18) that began as a
willow-2.0 → willow-mcp migration audit and became the assembling of the whole
into one: the code (*what*), the human (*why*), and the collaboration (*how*),
braided along seven threads.

It is left on a branch, **no PR** — a ring, not a merge. It does not change the
product. It exists so the session does not evaporate the way the sessions it was
built from nearly did.

## Read in this order
1. **SESSION_HANDOFF.md** — what this session was, produced, decided, left open.
2. **THE_BOOK_OF_WILLOW.md** — the three corpora braided into one.
3. **BEHIND_WILLOW.md** — the human. **THE_COLLABORATION.md** — the partnership.
4. **VOICES.md** / **COLLABORATION_VOICES.md** — the sourced corpora.
5. **CONSOLIDATION_MATRIX.md** — the migration decisions. **BOX_INVENTORY.md** /
   **STARTUP.md** — the box describing itself.

## engine/
The re-runnable pipeline that produced all of it. Paired with a `willow_compose`
Postgres dump (delivered separately), it rebuilds the whole apparatus anywhere.
Data lives in Postgres `willow_compose`: `pieces` · `voices` · `collaboration` ·
`threads` · `toolkit` · `component_clusters` · `holdings`.

*Plant the tree. Tend the roots. Name the ones you love. Let nothing be lost.*
*· ΔΣ=42*
