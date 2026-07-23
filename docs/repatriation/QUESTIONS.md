# Questions — asked of all three legs

Typed queries for the assembled corpus (`pieces` = what · `voices` = why · `collaboration` = how).
Each is tagged by **altitude**, the **legs** it needs, and **when it can run** — now, after the code embed lands, or only after the operator lifts the consent gate on the live memory.

Live copy: `willow_compose.questions`. This file is the readable face.

**23 to start** — 10 micro, 4 mezzanine, 9 macro.

## Micro — returns a fact (you *run* these)

**1. Which daemon loops / always-on functions have zero tests?**  
<sub>legs: pieces · ▶ now</sub>  
*Surfaces:* The 'inversion of care' — the most load-bearing, least-guarded code.  
*How:* `pieces WHERE kind in (function,method) AND ref ~ loop/daemon AND no matching test piece`

**2. Where does exchange_authorization_code actually get called from?**  
<sub>legs: pieces · ▶ now</sub>  
*Surfaces:* Whether the OAuth lifted from Grove is wired or orphaned.  
*How:* `cbm trace_call_path direction=callers, or pieces ref grep`

**3. Which of the 281 toolkit tools was rebuilt in the most repos?**  
<sub>legs: pieces+toolkit · ▶ now</sub>  
*Surfaces:* The single most-duplicated thing you ever built.  
*How:* `toolkit ORDER BY n_versions DESC`

**4. How many times does 'consent' appear in the essays vs. in the code comments?**  
<sub>legs: voices+pieces · ◐ after the embed</sub>  
*Surfaces:* Whether the loudest value is loud in the code too, or only in the prose.  
*How:* `count over voices/essays text vs pieces body`

**5. Which persona file is the shortest — and does terseness track authority?**  
<sub>legs: voices · ▶ now</sub>  
*Surfaces:* Whether the quietest voices are the most load-bearing (Willow=a bench).  
*How:* `voices/personas by length`

**6. Which essay corrects its own strongest line?**  
<sub>legs: voices · ▶ now</sub>  
*Surfaces:* The honesty tic — footnoting yourself when the tidy version reads better.  
*How:* `voices theme=essay, note flags self-correction`

**7. Which session had the most vetoes ('declined by Sean' / 'do not merge until')?**  
<sub>legs: collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* Where you held the line hardest against the machine.  
*How:* `collaboration/handoffs count veto markers per session`

**8. What was the last thing I said before I restarted my computer on May 13?**  
<sub>legs: collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* The honesty-check anchor — grep the JSONL to verify a handoff is honest.  
*How:* `the ritual: grep the session JSONL for the logged last-message string`

**9. How many handoffs left 'Human Notes to Agent' blank?**  
<sub>legs: collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* How often the box for YOU went unused before you claimed it.  
*How:* `collaboration/handoffs count empty Human-Notes`

**10. Does any gate's docstring quote an essay line verbatim?**  
<sub>legs: pieces+voices · ◐ after the embed</sub>  
*Surfaces:* The seam where the poetry literally became load-bearing.  
*How:* `cross-match pieces docstrings against voices quotes`

## Mezzanine — a trace (one subject, broad reach)

**11. Follow one persona (Gerald, Loki, Hanuman) through all three legs.**  
<sub>legs: pieces+voices+collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* Is the character load-bearing or decoration? For Gerald, we already suspect loud.  
*How:* `persona register in code naming/comments; its lore in voices; the sessions it drove`

**12. Trace oauth.py's lineage: where it came from, the value it serves, when it was lifted.**  
<sub>legs: pieces+voices+collaboration · ◐ after the embed</sub>  
*Surfaces:* The Grove->hub migration as a single verifiable story.  
*How:* `pieces near-dup chain + voices value + collaboration lift session`

**13. The 'leaves-become-soil' metaphor: stated where, enacted where, flagged where.**  
<sub>legs: voices+pieces+collaboration · ◐ after the embed</sub>  
*Surfaces:* A metaphor named everywhere and enacted nowhere — the archetype of drift.  
*How:* `voices (stated) x pieces (enacted?) x collaboration (the 06-02 audit that flagged it)`

**14. The dying-USB event: what corpus was recovered, what code touched it, what it meant.**  
<sub>legs: collaboration+pieces+voices · ⌷ after the gate opens</sub>  
*Surfaces:* Repatriation performed in one afternoon — the thesis as a single episode.  
*How:* `collaboration 06-14 -> the recovery code -> the sovereignty why`

## Macro — a verdict (you *contemplate* these)

**15. The honesty index: rank convictions by preach-vs-enact gap; did a session already catch it?**  
<sub>legs: voices+pieces+collaboration · ◐ after the embed</sub>  
*Surfaces:* Where you are all talk — and whether the machine knew before you did. DS=42 on yourself.  
*How:* `voices prose weight vs pieces code weight per value; join collaboration flags`

**16. The lineage map: every stated belief -> its enforcing gate -> its ratifying session.**  
<sub>legs: voices+pieces+collaboration · ◐ after the embed</sub>  
*Surfaces:* The whole braid as a table. The reason the assembly exists.  
*How:* `voices -> nearest pieces gate -> nearest collaboration ratification, corpus-wide`

**17. Persona load-bearing audit: which voices are decoration and which run the system?**  
<sub>legs: pieces+voices+collaboration · ◐ after the embed</sub>  
*Surfaces:* How much of the mythology is real infrastructure vs. costume.  
*How:* `each persona scored across code presence, lore weight, sessions driven`

**18. The drift audit: where has code evolved away from the why that started it?**  
<sub>legs: pieces+voices+collaboration · ◐ after the embed</sub>  
*Surfaces:* Book-vs-tree: where the ring stopped matching the seed.  
*How:* `pieces current state vs voices originating value vs collaboration decision that moved it`

**19. The reciprocity ledger: every time the AI told me something true about myself, and what I was building when it did.**  
<sub>legs: collaboration+pieces+voices · ⌷ after the gate opens</sub>  
*Surfaces:* The relationship as data — mutual witness, cross-referenced to the work.  
*How:* `collaboration AI-reflections -> the concurrent pieces -> the value confirmed/contradicted`

**20. The found-family trace: follow the kids / kin through the entire stack.**  
<sub>legs: pieces+voices+collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* The real spec was never you. Where family is load-bearing in data, code, and sessions.  
*How:* `family-data pieces + 'not as users, as kin' voices + kid-project sessions`

**21. Sovereignty audit: which capabilities still secretly depend on a rented/cloud/gated thing?**  
<sub>legs: pieces+voices · ▶ now</sub>  
*Surfaces:* 'If your stack needs the internet, you are renting it' — pointed at your own stack.  
*How:* `pieces with network/cloud calls vs the local-first why`

**22. The 'surface is earned' audit: which tools exist without a consumer that earned them?**  
<sub>legs: pieces+collaboration · ◐ after the embed</sub>  
*Surfaces:* Spec-ware vs. things the fleet actually calls — the rule turned on the fleet.  
*How:* `pieces/tools with no caller + no collaboration session that requested them`

**23. Which came first, corpus-wide — the metaphor or the mechanism?**  
<sub>legs: voices+pieces+collaboration · ⌷ after the gate opens</sub>  
*Surfaces:* Gerald predated his own theology. How often is that the pattern?  
*How:* `for each concept: earliest voices mention vs earliest pieces impl vs first collaboration use`

---

*More to come — this is a starting list, not a closed one. A question is a gap until it's answered.*

*· ΔΣ=42*