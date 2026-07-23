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
| F10 | The store-guard tripwire over-fires on payload prose | low | `gaps/75a2c8b5`; blocked willow_compose writes on the bare word 'records' (fired again on the final reconcile, caught instantly) |
| F11 | The gated memory is a commentary track, not a recording | — | `gated_runs/3795aeed`; Q8 05-13 sessions `turn_count:0` (deeds kept, voice lost); Q9 Human-Notes blank; Q14 meaning kept, operation not |
| F12 | Family is the spec, not a feature — proven by a sovereign *absence* | — | Q20: family-data apps absent from the corpus, held local; 320 consent/witness/care pieces; "not as users, as kin" |
| F13 | The metaphor predated the mechanism; Gerald is load-bearing | — | Q11/17/23: `ΔΣ=42`+soil are Gerald's gags; most "personas" are agents/modules; lore dates Nov-2024, code 2026 |
| F14 | The consolidation matrix is enact-blind (0/307 consider whether a piece runs) | med | `gaps/6ec60d31`; 3 `FOLD→mcp` verdicts backwards; `kart_migration/f9cdc57f`, `fork_triage/c22adf01` |

## Checklist

- [x] Three corpora assembled and braided (`threads`)
- [x] Session captured in native rituals (this file + `handoff-v3-the-assembling.md`)
- [x] Record left on a branch, no PR
- [x] All three corpora embedded (local CPU pipe, 29,432 + 76 + 42)
- [x] All 23 questions run, answered, persisted (`question_runs/b8c77fcb` + `gated_runs/*`)
- [x] `questions` table reconciled — **23 answered, 0 held**, every row with a provenance pointer
- [x] Consent gate opened by operator; nine gated questions answered via MCP tools (no bulk read)
- [x] Private specifics kept out of every durable artifact (structure only; held hardest on Q20)
- [x] Consolidation made honest (enact-axis): `gaps/6ec60d31`, `kart_migration/f9cdc57f`, `fork_triage/c22adf01`
- [x] Three gaps filed front-door (`1a68605b`, `75a2c8b5`, `6ec60d31`)
- [ ] Home for the assembled apparatus decided
- [ ] Act on a consolidation worklist (backwards folds / kart stage-5 / safe-app-store fork)

## Next bite

The questions are done; what remains is *action on the findings*: **(1)** decide where the
apparatus lives (engine rebuilds anywhere; dump restores). **(2)** Act on a consolidation
worklist. **(3)** Swap in a code-aware embedder and re-run the `pieces`-side questions —
the one move that sharpens every code-side number.

## Notes

This session is itself the material the `collaboration` corpus was harvested from — a
Willow session, now captured by Willow's own ritual so it doesn't evaporate. The human
side is answered too now: the gate opened, the nine ran, and the people were kept out of
the ledger while their *significance* was written into it. Q20's verdict stands as the
close: family is the spec, protected by being the one thing the system cannot see.

*· ΔΣ=42*
