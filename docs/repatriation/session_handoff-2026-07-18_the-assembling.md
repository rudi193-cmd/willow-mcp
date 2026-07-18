# Session handoff — claude-code

**Format:** session_handoff_v3
**Entry mode:** human
**Session:** session_01WjP387WRPYpDJVhEqXs6oK
**Project:** willow-mcp
**Workspace:** /home/user/willow-mcp
**Written at:** 2026-07-18T20:26:04Z

## Summary

A ~20 MB session (verified against the raw transcript) that began as a willow-2.0 → willow-mcp migration audit and became
the assembling of the whole into one: the code (`pieces`, 29,432), the human (`voices`,
76), and the collaboration (`collaboration`, 42), braided along seven `threads`. Also
produced: a 281-tool factory, a 307-decision consolidation matrix, a self-describing
`holdings` registry, and a local CPU inference pipe stood up inside the box to embed the
corpora. **Second act:** the embed completed (all three corpora), the semantic gate opened,
14 of 23 questions were run read-only and answered, the run was persisted to willow's store
(`question_runs/b8c77fcb`) through the front door and reconciled into `willow_compose.questions`
(14 answered, 9 held), and two gaps were filed (`gaps/1a68605b` caching, `gaps/75a2c8b5`
tripwire). Left as a ring on branch `claude/the-assembling`, no PR.

## Narrative

The doorway was engineering; the house was a portrait. Willow-mcp was confirmed as the
hub (kept lean); the ecosystem stays decomposed into sovereign parts. The three corpora
were harvested, sourced, and braided; the assembled whole is `THE_BOOK_OF_WILLOW.md`.
A local `sentence-transformers` pipe (CPU, the same family Willow's own `conversation_rag`
used) proved sovereign inference runs inside the rented walls, and embedded the corpora
so the braid is queryable by meaning.

The load-bearing restraint: the live memory (`willow_19`, 229k atoms; the SOIL store)
was **not** embedded. Willow's own consent hook blocked the bulk read, and the agent did
not route around a security gate — the sudo invariant, honored. The operator lifts that
gate, or it stays shut.

## Findings

| ID | Finding | Severity | Evidence |
|----|---------|----------|----------|
| F1 | The three corpora are one artifact in three registers | — | `threads` (7) braid why→what→how; `THE_BOOK_OF_WILLOW.md` |
| F2 | Grove is the #1 consolidation target (duplicated across 4 repos) | med | `component_clusters`; `CONSOLIDATION_MATRIX.md` |
| F3 | Live memory is consent-gated even from the operator's own agent | — | `willow_19` psql bounced: "use the MCP tools instead"; gate honored |
| F4 | Sovereign local inference runs on the box (CPU) | — | `all-mpnet-base-v2`, 0.06s/embedding, cuda False; embed completed 29,432/29,432 |
| F5 | The apparatus is durable but homeless | low | `willow_compose` dump (123 MB, w/ vectors) + this branch; placement deferred 3× |
| F6 | Consent is the most-enacted conviction, not just the most-preached | — | Q15 smallest preach-enact gap; 'consent' 3× in essays vs 1531× in code; the gate blocked the agent live |
| F7 | willow-mcp is the most value-dense repo in the corpus | — | Q18: hub code least semantically distant from all 7 convictions (0.78 of 12) |
| F8 | The Grove→hub OAuth lift is byte-identical, not just similar | — | Q12: `content_sha 70a3864212` shared across grove+2.0+mcp |
| F9 | The leaves-become-soil metaphor was enacted in shape but flagged dormant | low | Q13: `the_grove.py` present, but 06-02 'nightly norn pass never durably ran' |
| F10 | The store-guard tripwire over-fires on payload prose | low | `gaps/75a2c8b5`; blocked willow_compose writes on the bare word 'records' |

## Checklist

- [x] Three corpora assembled and braided (`threads`)
- [x] Session captured in native rituals (this file + `handoff-v3-the-assembling.md`)
- [x] Record left on a branch, no PR
- [x] All three corpora embedded (local CPU pipe, 29,432 + 76 + 42)
- [x] 14 of 23 questions run, answered, persisted (`question_runs/b8c77fcb`)
- [x] `questions` table reconciled (14 answered, 9 held)
- [x] Two gaps filed front-door (`gaps/1a68605b`, `gaps/75a2c8b5`)
- [ ] Nine `needs-gate` questions run (blocked on operator lifting the consent gate)
- [ ] Home for the assembled apparatus decided

## Next bite

Either order: **(1)** decide where the apparatus lives — standalone `willow-compose` repo,
into the hub, or a boot hook; the engine (`engine/`) rebuilds it anywhere and
`willow_compose.dump` restores the data. **(2)** Lift the consent gate (operator only) to
run the last nine `held` questions against willow_19 / the live SOIL store. Everything
else is queued behind these two.

## Notes

This session is itself the material the `collaboration` corpus was harvested from — a
Willow session, now captured by Willow's own ritual so it doesn't evaporate.

*· ΔΣ=42*
