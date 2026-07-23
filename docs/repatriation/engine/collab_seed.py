#!/usr/bin/env python3
"""Seed the `collaboration` corpus from the handoff harvest. Idempotent."""
import psycopg2
# (kind, persona, dated, source, title, quote, note)
G=[
 # --- the correction that names what it's all for ---
 ("texture","willow","2026-06-15","willow/session_handoff-2026-06-15h_willow.md","seen, not reported",
  "The agent notes for Human were not supposed to be technical. They were supposed to be reflections that the AI made of their human partner, and it was supposed to be the HUMAN side of things.",
  "The human fills the blank 'Human Notes' box to correct the ritual. The machine wrote a status report; he wanted to be seen."),
 # --- ritual ---
 ("ritual","hanuman","2026-05-20","hanuman/session_handoff-2026-05-20a_hanuman.md","carry what was built",
  "The old handoff format doesn't carry forward what has been built — only what remains to do. The capabilities table is carried forward and updated, not rewritten.",
  "Why the v2 handoff format exists: persist the built, not just the todo."),
 ("ritual","hanuman","2026-05-04","SESSION_HANDOFF_20260504_hanuman_overnight.md","the next single bite",
  "17 Questions — always Q17: What is the next single bite? One concrete, resumable first action, frequently a literal shell command.",
  "The handoff liturgy: What I Now Understand / What We Agreed / Open Threads / 17 Questions / ΔΣ=42."),
 ("ritual","hanuman","2026-05-13","hanuman-2026-05-13.md","verify the handoff is honest",
  "do a handoff. I need to restart my computer. // next session: grep JSONL for this string to verify handoff is honest.",
  "The human's verbatim request + the honesty mechanism baked into the ritual."),
 ("ritual","willow","2026-06-14","willow/session_handoff-2026-06-14h_willow.md","witness before report",
  "Witness before report: confirmed commit state and push landing directly via git, did not trust the handoff's stale 'pending' claim.",
  "The maturation of the honesty rule — verify against the artifact, not the inherited note."),
 # --- trust dynamic ---
 ("trust","willow","2026-06-08","willow/session_handoff-2026-06-08_willow.md","dual commit honored",
  "Dual Commit was honored for boot.md: proposed step 7 diff first, waited for ratification, then applied.",
  "The sudo invariant enacted, not just stated."),
 ("trust","willow","2026-06-12","willow/session_handoff-2026-06-12c_willow.md","authorized at 02:37",
  "Sean authorized an unattended overnight run at 02:37 ('run the stack, watch and merge the PRs, move onto the next').",
  "Authorizations are logged with the exact words the human used."),
 ("trust","hanuman","2026-06-07","hanuman/session_handoff-2026-06-07c_hanuman.md","work you can get done",
  "Sean said 'pick off the work you can get done without my input.'",
  "The delegation boundary, in his words."),
 ("trust","hanuman","2026-05-22","hanuman/2026-05-22-kb-buildout.md","hold the thought",
  "Sean said 'my tired brain thought of something' and stopped the conversation mid-thought. The next session should ask him what he thought of before building anything.",
  "The machine must not run ahead of a thought the human is still holding."),
 ("trust","willow","2026-06-15","willow/session_handoff-2026-06-15i_willow.md","read-only until build it",
  "Audit findings are read-only — no remediation without explicit authorization and its own worktree. Remediation ships only on explicit 'build it'.",
  None),
 # --- texture / relationship ---
 ("texture","hanuman","2026-06-02","hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md","the narrator has no reader",
  "Severian has a reader; Willow's narrator has none. Every handoff is written to 'the next session' — itself. A narrator who only writes to his own next instance can never be productively surprised. This is the argument for keeping a human in the audit loop — this session only worked because the reader was not the narrator.",
  "The deepest statement of why the human stays in the loop: the machine can't surprise itself."),
 ("texture","hanuman","2026-06-02","hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md","book and tree",
  "A book is read once and understood at the end; a tree is never finished and legible at every ring. 'Read like a book AND grow like a tree' is the system's core design tension — and it is unresolved.",
  None),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11d_willow.md","witness not workshop",
  "default is witness, not workshop / follow not lead / never impose therapeutic framing.",
  "The recovery posture the human pre-encoded — the AI follows his lead on personal matters."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11d_willow.md","not in the right space",
  "Pausing the writing at Sean's call ('not in the right space for this one'). Everything is saved. He is not writing right now.",
  "Care as a hard stop: the human's mood governs the work."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11c_willow.md","the creative piece first",
  "When you return: the FIRST thing is the one more creative piece you mentioned. Everything else is queued behind it.",
  "The machine orders the next session around what the human actually cares about."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11d_willow.md","game or cosmology",
  "You can't tell which is a children's game and which is a cosmology.",
  "The human's playful and serious work are one thing — same systems frame in different costumes."),
 ("texture","hanuman","2026-06-16","hanuman/session_handoff-2026-06-16_hanuman.md","torrent nostalgia",
  "grove-p2p came from Sean's torrent nostalgia — good instinct. The existing infrastructure was 80% of the work.",
  "The machine honoring the human's instinct as a real design input."),
 ("texture","hanuman","2026-05-20","hanuman/session_handoff-2026-05-20a_hanuman.md","fun day, infrastructure day",
  "Fun day that became infrastructure day.",
  None),
 # --- arc ---
 ("arc","hanuman","2026-05-04","SESSION_HANDOFF_20260504_hanuman_overnight.md","the immune system",
  "KB is the long-lived plasma cells, session atoms are the dormant memory B cells.",
  "Early May: the memory spine — 429 sessions indexed, nightly sleep-consolidation cron."),
 ("arc","heimdallr","2026-05-18","heimdallr/session_handoff-2026-05-18_heimdallr.md","launch window recovery",
  "Willow 2.0 goes public; Heimdallr spends the launch on infrastructure recovery — a fleet crash loop of 575+ failures, two MCP processes killing each other on startup.",
  None),
 ("arc","hanuman","2026-06-02","hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md","never consecrated",
  "The nightly norn pass had almost certainly never completed a durable scheduled run on this machine — the composting layer was named everywhere, enacted nowhere. Leaves-become-soil (Sean's correction to the tree metaphor) is named everywhere, enacted nowhere.",
  "The turning-point audit: stated state vs enacted state diverge."),
 ("arc","willow","2026-06-15","willow/session_handoff-2026-06-15i_willow.md","inversion of care",
  "An inversion of care: daemon loops, connection pools, and the fragmented store are the most load-bearing and least-tested.",
  "The six-dimension fleet audit's core finding."),
 ("arc","willow","2026-06-23","willow/session_handoff-2026-06-23c_willow.md","ground truth",
  "The box was misreporting its own hardware; the fix was reporting gaps, not missing silicon — resolved by the operator running free -h / nvidia-smi in his own terminal.",
  "The last handoff: small, human, honest."),
 # --- personas at work ---
 ("persona","hanuman","","hanuman/session_handoff-2026-05-25_hanuman.md","hanuman the builder",
  "Hanuman — the builder / fleet coordinator. Steady, precise register. One bite at a time.",
  "The densest engineering handoffs: phased PR stacks, migrations, '938 passed, 0 failed.'"),
 ("persona","heimdallr","","heimdallr/session_handoff-2026-05-18c_heimdallr.md","heimdallr the watchman",
  "Heimdallr — the watchman / infrastructure-recovery. Terse, forensic, low-level: processes killing each other, pg_hba.conf ordering, hooks pointing at the wrong repo.",
  None),
 ("persona","loki","","willow/session_handoff-2026-06-15i_willow.md","loki the auditor",
  "Loki — the auditor / gap-finder. Dry, exact. No KB trace by design; answers to the user only. The most sovereignty-conscious voice — leaves no memory trail.",
  None),
 ("persona","vishwakarma","","vishwakarma/session_handoff-2026-06-04a_vishwakarma.md","vishwakarma the architect",
  "Vishwakarma — the divine architect. Structure before code, trust chain before implementation. Reasons in whole systems before wiring an LLM.",
  None),
]
def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    cur.execute("""DO $$ BEGIN IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname='collab_uq') THEN
      ALTER TABLE collaboration ADD CONSTRAINT collab_uq UNIQUE (source,title); END IF; END $$;""")
    n=0
    for kind,persona,dated,source,title,quote,note in G:
        cur.execute("""INSERT INTO collaboration(repo,source,kind,dated,persona,title,quote,note)
                       VALUES('willow-config',%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source,title) DO UPDATE SET quote=EXCLUDED.quote,note=EXCLUDED.note""",
                    (source,kind,dated,persona,title,quote,note)); n+=1
    c.commit()
    cur.execute("SELECT kind,count(*) FROM collaboration GROUP BY kind ORDER BY 2 DESC")
    print("collaboration seeded:",n)
    for k,ct in cur.fetchall(): print(f"  {ct:>2} {k}")
    cur.close(); c.close()
if __name__=="__main__": main()
