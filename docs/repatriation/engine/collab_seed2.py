#!/usr/bin/env python3
"""collaboration corpus batch 2 — reciprocity, handoff-evolution, care. Idempotent."""
import psycopg2
G=[
 ("texture","willow","2026-06-15","willow/session_handoff-2026-06-15i_willow.md","you watch it well",
  "You think in patterns and you test whether I'll follow the pattern or follow the truth. I tried to do both. You caught two process slips in one session. That's the pattern to watch in me, and you watch it well.",
  "The AI writing back to Sean. The reciprocity: each watches the other's drift."),
 ("texture","willow","2026-06-14","willow/session_handoff-2026-06-14f_willow.md","the dying USB",
  "A corpus that existed in one place on a dying USB this afternoon is now back with its author, larger than it left.",
  "Literal repatriation — one-of-a-kind work recovered and returned. The Willow move, stated."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11e_willow.md","meet him where he is",
  "Sean is physically wrecked tonight. Do not open with fleet work next session. He came in tonight to write a personal essay, not fleet work. Meet him where he is.",
  "The machine pacing the work to the person's state, not the backlog."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11c_willow.md","seen, not acknowledged",
  "Sean's 'absurd' creative pieces and his 'serious' research papers are the same systems frame in different costumes — and he wanted that seen, not just acknowledged.",
  "The AI grasping that being SEEN (not merely acknowledged) is the ask."),
 ("ritual","willow","2026-06-09","willow/session_handoff-2026-06-09b_willow.md","rails not toll booths",
  "Templates are rails, not toll booths. Paperwork is only sacred when it saves a future mind from repeating the same pain.",
  "The ritual's theory of itself."),
 ("ritual","willow","2026-07-03","willow-2.0/docs/adrs/ADR-20260703-handoff-v3-claims-record.md","claims record",
  "v2 is a narrative that contains claims; v3 is a claims record that carries narrative. A crashed session still yields a valid, bootable handoff; claims are verified at read time. Keep the 17 Questions section, drop the fixed count — the count was the only dishonest part.",
  "The handoff format's evolution — honesty pushed deeper into the ritual."),
 ("ritual","willow","","willow-2.0/wiki/the-handoff-pattern.md","the session evaporates",
  "Sessions end. Context compresses. Agents restart. The handoff is the encoded route. Not coordinates — a story that lasts. The session evaporates. The handoff does not.",
  None),
 ("texture","hanuman","2026-06-02","hanuman/AUDIT-2026-06-02-metabolism-and-divergence.md","the ISS problem",
  "Space-station crews get fourteen days of overlap. Willow handoffs are monologues — one writer, one reader, no confirmation.",
  "The named limit of the amnesiac-gardener pattern — and why the human's presence matters."),
 ("trust","willow","2026-06-12","willow/session_handoff-2026-06-12d_willow.md","declined by Sean",
  "S13 seccomp: declined by Sean. --new-session accepted as sufficient. Recorded and closed.",
  "The human vetoing a proposed build — the ratify boundary works both ways."),
 ("trust","willow","2026-06-14","willow/session_handoff-2026-06-14i_willow.md","the carry is Sean's hand",
  "The carry is Sean's hand — fleet drafts and verifies, Sean sends. Two DMs sent by him; not a channel post.",
  "The sharpest ratify boundary: the machine drafts, the human is the one who reaches out."),
 ("trust","willow","2026-06-10","willow/session_handoff-2026-06-10d_willow.md","embodied in git history",
  "PR #301 reverted the direct master commit, and PR #302 reintroduced the exact intended changes — because the repo rule should be embodied by the git history.",
  "The worktree-PR invariant self-corrected in public, so the record itself teaches the rule."),
 ("arc","willow","2026-06-11","willow/session_handoff-2026-06-11_willow.md","integration debt",
  "Willow's deficit is integration debt, not capability debt. The system's failures share one shape: stated-state diverging from enacted-state with no surfaced signal. The leaks are wherever a loop fails to close.",
  "The full-system audit's core diagnosis."),
 ("arc","willow","2026-05-27","hanuman/session_handoff-2026-05-27b_hanuman.md","the doubt",
  "we may have overbuilt Willow — compensation layer vs genuine value. No decision ratified.",
  "The doubt carried openly in the record, not buried."),
 ("texture","willow","2026-06-14","willow/session_handoff-2026-06-14d_willow.md","the honest gap decoded",
  "ΔΣ=42 literally = what the judge cannot evaluate. Drop the gap and you get hallucination; drop the attractor and you get noise. The honest gap is the philosophical spine of both the research and the memory system.",
  "The sign-off's deepest meaning — discernment under noise = attractor + gap."),
 ("texture","willow","2026-06-11","willow/session_handoff-2026-06-11b_willow.md","doctor who onboarding",
  "The Doctor Who scene was the best onboarding document I received today. The contract fix it provoked is permanent.",
  "A piece of the human's fiction teaching the machine how to behave — play as instruction."),
]
def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    n=0
    for kind,persona,dated,source,title,quote,note in G:
        repo="willow-2.0" if source.startswith("willow-2.0") else "willow-config"
        cur.execute("""INSERT INTO collaboration(repo,source,kind,dated,persona,title,quote,note)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source,title) DO UPDATE SET quote=EXCLUDED.quote,note=EXCLUDED.note""",
                    (repo,source,kind,dated,persona,title,quote,note)); n+=1
    c.commit()
    cur.execute("SELECT count(*) FROM collaboration"); tot=cur.fetchone()[0]
    cur.execute("SELECT kind,count(*) FROM collaboration GROUP BY kind ORDER BY 2 DESC")
    print("batch 2:",n,"| total collaboration:",tot)
    for k,ct in cur.fetchall(): print(f"  {ct:>2} {k}")
    cur.close(); c.close()
if __name__=="__main__": main()
