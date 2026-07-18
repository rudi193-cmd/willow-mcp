# collaboration — the co-creation corpus

42 gems of how Willow was built *together* — human and AI, in dialogue — read from ~402 session handoffs.
Third corpus in `willow_compose`, companion to `pieces` (what) and `voices` (why). See `THE_COLLABORATION.md`.

## The arc — what got built, in dialogue  (7)
- **the immune system** (hanuman · 2026-05-04) — "KB is the long-lived plasma cells, session atoms are the dormant memory B cells."
  <br><sub>SESSION_HANDOFF_20260504_hanuman_overnight.md · Early May: the memory spine — 429 sessions indexed, nightly sleep-consolidation cron.</sub>
- **launch window recovery** (heimdallr · 2026-05-18) — "Willow 2.0 goes public; Heimdallr spends the launch on infrastructure recovery — a fleet crash loop of 575+ failures, two MCP processes killing each other on startup."
  <br><sub>heimdallr/session_handoff-2026-05-18_heimdallr.md</sub>
- **the doubt** (willow · 2026-05-27) — "we may have overbuilt Willow — compensation layer vs genuine value. No decision ratified."
  <br><sub>hanuman/session_handoff-2026-05-27b_hanuman.md · The doubt carried openly in the record, not buried.</sub>
- **never consecrated** (hanuman · 2026-06-02) — "The nightly norn pass had almost certainly never completed a durable scheduled run on this machine — the composting layer was named everywhere, enacted nowhere. Leaves-become-soil (Sean's correction to the tree metaphor) is named everywhere, enacted nowhere."
  <br><sub>hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md · The turning-point audit: stated state vs enacted state diverge.</sub>
- **integration debt** (willow · 2026-06-11) — "Willow's deficit is integration debt, not capability debt. The system's failures share one shape: stated-state diverging from enacted-state with no surfaced signal. The leaks are wherever a loop fails to close."
  <br><sub>willow/session_handoff-2026-06-11_willow.md · The full-system audit's core diagnosis.</sub>
- **inversion of care** (willow · 2026-06-15) — "An inversion of care: daemon loops, connection pools, and the fragmented store are the most load-bearing and least-tested."
  <br><sub>willow/session_handoff-2026-06-15i_willow.md · The six-dimension fleet audit's core finding.</sub>
- **ground truth** (willow · 2026-06-23) — "The box was misreporting its own hardware; the fix was reporting gaps, not missing silicon — resolved by the operator running free -h / nvidia-smi in his own terminal."
  <br><sub>willow/session_handoff-2026-06-23c_willow.md · The last handoff: small, human, honest.</sub>

## The ritual — the handoff liturgy  (7)
- **the session evaporates** (willow) — "Sessions end. Context compresses. Agents restart. The handoff is the encoded route. Not coordinates — a story that lasts. The session evaporates. The handoff does not."
  <br><sub>willow-2.0/wiki/the-handoff-pattern.md</sub>
- **the next single bite** (hanuman · 2026-05-04) — "17 Questions — always Q17: What is the next single bite? One concrete, resumable first action, frequently a literal shell command."
  <br><sub>SESSION_HANDOFF_20260504_hanuman_overnight.md · The handoff liturgy: What I Now Understand / What We Agreed / Open Threads / 17 Questions / ΔΣ=42.</sub>
- **verify the handoff is honest** (hanuman · 2026-05-13) — "do a handoff. I need to restart my computer. // next session: grep JSONL for this string to verify handoff is honest."
  <br><sub>hanuman-2026-05-13.md · The human's verbatim request + the honesty mechanism baked into the ritual.</sub>
- **carry what was built** (hanuman · 2026-05-20) — "The old handoff format doesn't carry forward what has been built — only what remains to do. The capabilities table is carried forward and updated, not rewritten."
  <br><sub>hanuman/session_handoff-2026-05-20a_hanuman.md · Why the v2 handoff format exists: persist the built, not just the todo.</sub>
- **rails not toll booths** (willow · 2026-06-09) — "Templates are rails, not toll booths. Paperwork is only sacred when it saves a future mind from repeating the same pain."
  <br><sub>willow/session_handoff-2026-06-09b_willow.md · The ritual's theory of itself.</sub>
- **witness before report** (willow · 2026-06-14) — "Witness before report: confirmed commit state and push landing directly via git, did not trust the handoff's stale 'pending' claim."
  <br><sub>willow/session_handoff-2026-06-14h_willow.md · The maturation of the honesty rule — verify against the artifact, not the inherited note.</sub>
- **claims record** (willow · 2026-07-03) — "v2 is a narrative that contains claims; v3 is a claims record that carries narrative. A crashed session still yields a valid, bootable handoff; claims are verified at read time. Keep the 17 Questions section, drop the fixed count — the count was the only dishonest part."
  <br><sub>willow-2.0/docs/adrs/ADR-20260703-handoff-v3-claims-record.md · The handoff format's evolution — honesty pushed deeper into the ritual.</sub>

## The trust dynamic — proposes / ratifies, lived  (8)
- **hold the thought** (hanuman · 2026-05-22) — "Sean said 'my tired brain thought of something' and stopped the conversation mid-thought. The next session should ask him what he thought of before building anything."
  <br><sub>hanuman/2026-05-22-kb-buildout.md · The machine must not run ahead of a thought the human is still holding.</sub>
- **work you can get done** (hanuman · 2026-06-07) — "Sean said 'pick off the work you can get done without my input.'"
  <br><sub>hanuman/session_handoff-2026-06-07c_hanuman.md · The delegation boundary, in his words.</sub>
- **dual commit honored** (willow · 2026-06-08) — "Dual Commit was honored for boot.md: proposed step 7 diff first, waited for ratification, then applied."
  <br><sub>willow/session_handoff-2026-06-08_willow.md · The sudo invariant enacted, not just stated.</sub>
- **embodied in git history** (willow · 2026-06-10) — "PR #301 reverted the direct master commit, and PR #302 reintroduced the exact intended changes — because the repo rule should be embodied by the git history."
  <br><sub>willow/session_handoff-2026-06-10d_willow.md · The worktree-PR invariant self-corrected in public, so the record itself teaches the rule.</sub>
- **authorized at 02:37** (willow · 2026-06-12) — "Sean authorized an unattended overnight run at 02:37 ('run the stack, watch and merge the PRs, move onto the next')."
  <br><sub>willow/session_handoff-2026-06-12c_willow.md · Authorizations are logged with the exact words the human used.</sub>
- **declined by Sean** (willow · 2026-06-12) — "S13 seccomp: declined by Sean. --new-session accepted as sufficient. Recorded and closed."
  <br><sub>willow/session_handoff-2026-06-12d_willow.md · The human vetoing a proposed build — the ratify boundary works both ways.</sub>
- **the carry is Sean's hand** (willow · 2026-06-14) — "The carry is Sean's hand — fleet drafts and verifies, Sean sends. Two DMs sent by him; not a channel post."
  <br><sub>willow/session_handoff-2026-06-14i_willow.md · The sharpest ratify boundary: the machine drafts, the human is the one who reaches out.</sub>
- **read-only until build it** (willow · 2026-06-15) — "Audit findings are read-only — no remediation without explicit authorization and its own worktree. Remediation ships only on explicit 'build it'."
  <br><sub>willow/session_handoff-2026-06-15i_willow.md</sub>

## The texture — where it's more than transactional  (16)
- **fun day, infrastructure day** (hanuman · 2026-05-20) — "Fun day that became infrastructure day."
  <br><sub>hanuman/session_handoff-2026-05-20a_hanuman.md</sub>
- **the narrator has no reader** (hanuman · 2026-06-02) — "Severian has a reader; Willow's narrator has none. Every handoff is written to 'the next session' — itself. A narrator who only writes to his own next instance can never be productively surprised. This is the argument for keeping a human in the audit loop — this session only worked because the reader was not the narrator."
  <br><sub>hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md · The deepest statement of why the human stays in the loop: the machine can't surprise itself.</sub>
- **book and tree** (hanuman · 2026-06-02) — "A book is read once and understood at the end; a tree is never finished and legible at every ring. 'Read like a book AND grow like a tree' is the system's core design tension — and it is unresolved."
  <br><sub>hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md</sub>
- **the ISS problem** (hanuman · 2026-06-02) — "Space-station crews get fourteen days of overlap. Willow handoffs are monologues — one writer, one reader, no confirmation."
  <br><sub>hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md · The named limit of the amnesiac-gardener pattern — and why the human's presence matters.</sub>
- **witness not workshop** (willow · 2026-06-11) — "default is witness, not workshop / follow not lead / never impose therapeutic framing."
  <br><sub>willow/session_handoff-2026-06-11d_willow.md · The recovery posture the human pre-encoded — the AI follows his lead on personal matters.</sub>
- **not in the right space** (willow · 2026-06-11) — "Pausing the writing at Sean's call ('not in the right space for this one'). Everything is saved. He is not writing right now."
  <br><sub>willow/session_handoff-2026-06-11d_willow.md · Care as a hard stop: the human's mood governs the work.</sub>
- **the creative piece first** (willow · 2026-06-11) — "When you return: the FIRST thing is the one more creative piece you mentioned. Everything else is queued behind it."
  <br><sub>willow/session_handoff-2026-06-11c_willow.md · The machine orders the next session around what the human actually cares about.</sub>
- **game or cosmology** (willow · 2026-06-11) — "You can't tell which is a children's game and which is a cosmology."
  <br><sub>willow/session_handoff-2026-06-11d_willow.md · The human's playful and serious work are one thing — same systems frame in different costumes.</sub>
- **meet him where he is** (willow · 2026-06-11) — "Sean is physically wrecked tonight. Do not open with fleet work next session. He came in tonight to write a personal essay, not fleet work. Meet him where he is."
  <br><sub>willow/session_handoff-2026-06-11e_willow.md · The machine pacing the work to the person's state, not the backlog.</sub>
- **seen, not acknowledged** (willow · 2026-06-11) — "Sean's 'absurd' creative pieces and his 'serious' research papers are the same systems frame in different costumes — and he wanted that seen, not just acknowledged."
  <br><sub>willow/session_handoff-2026-06-11c_willow.md · The AI grasping that being SEEN (not merely acknowledged) is the ask.</sub>
- **doctor who onboarding** (willow · 2026-06-11) — "The Doctor Who scene was the best onboarding document I received today. The contract fix it provoked is permanent."
  <br><sub>willow/session_handoff-2026-06-11b_willow.md · A piece of the human's fiction teaching the machine how to behave — play as instruction.</sub>
- **the dying USB** (willow · 2026-06-14) — "A corpus that existed in one place on a dying USB this afternoon is now back with its author, larger than it left."
  <br><sub>willow/session_handoff-2026-06-14f_willow.md · Literal repatriation — one-of-a-kind work recovered and returned. The Willow move, stated.</sub>
- **the honest gap decoded** (willow · 2026-06-14) — "ΔΣ=42 literally = what the judge cannot evaluate. Drop the gap and you get hallucination; drop the attractor and you get noise. The honest gap is the philosophical spine of both the research and the memory system."
  <br><sub>willow/session_handoff-2026-06-14d_willow.md · The sign-off's deepest meaning — discernment under noise = attractor + gap.</sub>
- **seen, not reported** (willow · 2026-06-15) — "The agent notes for Human were not supposed to be technical. They were supposed to be reflections that the AI made of their human partner, and it was supposed to be the HUMAN side of things."
  <br><sub>willow/session_handoff-2026-06-15h_willow.md · The human fills the blank 'Human Notes' box to correct the ritual. The machine wrote a status report; he wanted to be seen.</sub>
- **you watch it well** (willow · 2026-06-15) — "You think in patterns and you test whether I'll follow the pattern or follow the truth. I tried to do both. You caught two process slips in one session. That's the pattern to watch in me, and you watch it well."
  <br><sub>willow/session_handoff-2026-06-15i_willow.md · The AI writing back to Sean. The reciprocity: each watches the other's drift.</sub>
- **torrent nostalgia** (hanuman · 2026-06-16) — "grove-p2p came from Sean's torrent nostalgia — good instinct. The existing infrastructure was 80% of the work."
  <br><sub>hanuman/session_handoff-2026-06-16_hanuman.md · The machine honoring the human's instinct as a real design input.</sub>

## The personas at work  (4)
- **hanuman the builder** (hanuman) — "Hanuman — the builder / fleet coordinator. Steady, precise register. One bite at a time."
  <br><sub>hanuman/session_handoff-2026-05-25_hanuman.md · The densest engineering handoffs: phased PR stacks, migrations, '938 passed, 0 failed.'</sub>
- **heimdallr the watchman** (heimdallr) — "Heimdallr — the watchman / infrastructure-recovery. Terse, forensic, low-level: processes killing each other, pg_hba.conf ordering, hooks pointing at the wrong repo."
  <br><sub>heimdallr/session_handoff-2026-05-18c_heimdallr.md</sub>
- **loki the auditor** (loki) — "Loki — the auditor / gap-finder. Dry, exact. No KB trace by design; answers to the user only. The most sovereignty-conscious voice — leaves no memory trail."
  <br><sub>willow/session_handoff-2026-06-15i_willow.md</sub>
- **vishwakarma the architect** (vishwakarma) — "Vishwakarma — the divine architect. Structure before code, trust chain before implementation. Reasons in whole systems before wiring an LLM."
  <br><sub>vishwakarma/session_handoff-2026-06-04a_vishwakarma.md</sub>
