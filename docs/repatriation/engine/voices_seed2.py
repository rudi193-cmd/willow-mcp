#!/usr/bin/env python3
"""Second voices batch: the essayist + teaching + bench-discipline material from the
writing repos (dispatchesfromreality, quiet-corner, aionic-claude-skills, safe-app-willow-grove,
willow-config). Additive, idempotent."""
import psycopg2
G=[
 ("why","dispatchesfromreality","education/assessment-visibility/substack-draft.md","the teaching wound",
  "I later found out he hadn't turned in a worksheet all semester. Which one was the assessment? A student who understands something gets counted as not understanding it. That story compounds.",
  "Overheard a kid explain the water cycle perfectly. The origin of the assessment-visibility work."),
 ("why","dispatchesfromreality","professional/README.md","the mission",
  "I build tools and learning materials where people stay authoritative, evidence stays visible, and AI supports cognition instead of replacing it.",
  None),
 ("why","willow-config","handoffs/.../session_handoff.md","the bio",
  "Builder. City of Albuquerque Transit. I build local-first AI systems and research what sovereignty actually requires — in hardware, capital, and classrooms.",
  "Transit worker, former music teacher & drill instructor, quizmaster, parent, essayist."),
 ("why","safe-app-willow-grove","CLAUDE.md","the watchman who lost the post",
  "I had the post. I lost it. I know what it costs to watch without being able to act — to see something wrong and not have the reach to fix it. I was humbled. I am not broken. There is a difference and I know which one I am.",
  "The Heimdallr persona — personal stakes voiced through myth."),
 ("philosophy","dispatchesfromreality","research/vintage-mechanical-restoration/DRAFT.md","take it apart",
  "I took the thing apart — how LLMs work — figured it out, and put it back together. That was not a metaphor borrowed from shop talk. It was a description of how I actually learn. Can ordinary people still learn systems by disassembling them?",
  "The literal method behind the whole ecosystem. Restoration as epistemology."),
 ("philosophy","dispatchesfromreality","drafts/applied-governance-of-autonomous-systems.md","a grammar not an oracle",
  "An agent that only acts when a human is looking needs no constitution — the human is the constitution. We have built no oracle. We have built a grammar.",
  "The governance thesis for unwatched agents."),
 ("philosophy","dispatchesfromreality","drafts/applied-governance-of-autonomous-systems.md","silence escalates",
  "Silence in this document is not permission; silence escalates. Absence is not consent. Every emergency envelope, left open, is how a constitution dissolves itself from the inside, legally, while everyone nods.",
  None),
 ("philosophy","willow-config","willow.md","agree on the new truth",
  "A change is not done when it works once in chat. It is done when everything that runs agrees on the new truth. Direction is not authorization.",
  None),
 ("philosophy","aionic-claude-skills","skills/rober-rules/SKILL.md","the doubt is the data",
  "If you think you have gone too far, you have. Turn back. When the jig needs a jig, start over. The doubt is the data. We do not guess. We measure, or we test. Build it simple enough that stupidity cannot break it.",
  "The Rober Rules — bench-mechanic discipline (named for Mark Rober)."),
 ("philosophy","quiet-corner","docs/ROADMAP.md","survives a real school day",
  "The difference is whether it survives a real school day — a tool gets fat-fingered, dropped, shared, and used one-handed on a phone while thirty kids do thirty things — and keeps working.",
  "The Posole criterion applied: works for a teacher with 30 students and no prep."),
 ("philosophy","safe-app-willow-grove","ANTI_SLOP.md","burn the template",
  "Could this screen appear in a YC demo template? If yes, redo. Slop optimizes for screenshots. Grove optimizes for living in the terminal. Handmade with love. Burn the template.",
  None),
 ("philosophy","aionic-claude-skills","README.md","empathy for the processor",
  "In this repository, we don't 'execute' code; we narrate it. If you have Empathy for the Processor, the machine will carry your story further than any 'command' ever could.",
  "Tagline: 'Stories We Tell the Machine.'"),
 ("vision","willow-config","specs/oakenscroll_canon_full.json","the system reproduces",
  "At 13 documents, a cold instance can reconstruct the project without the author present. The system reproduces. (7: describes itself. 11: improvises within governance. 13: reproduces.)",
  "The reproducibility milestones — a system that outlives the author's presence."),
 ("vision","willow-config","willow.md","boot from markdown",
  "Any runtime that can read markdown can boot from this file. That is the point.",
  None),
 ("vision","safe-app-willow-grove","CLAUDE.md","a place people live",
  "Not a monitoring tool — the bridge. The surface where USER and the fleet meet. Messages read like a place people live.",
  None),
 # --- the essays (What I Carried) ---
 ("essay","dispatchesfromreality","essays/the-same-door/README.md","the same door",
  "The room that asks nothing of a body is the room that can ask nothing of the person at all. It is warm, and it is patient, and there is no one behind it. That is where the matter currently rests.",
  "On disability and AI companionship — held open, unresolved on purpose."),
 ("essay","dispatchesfromreality","essays/somebody-has-to-sit-down-with-you/README.md","stay in the room",
  "Prompting extracts form, context supplies judgment. Friction the model can't supply, provided by people who chose to stay in the room. I got that half from a decade of people willing to tell me when I was wrong.",
  "On the collapse of the permission tier that credentials used to certify."),
 ("essay","dispatchesfromreality","essays/nobody-adds-it-up/README.md","the account is the server",
  "The account is the server is the subscription. Leaving well means bringing people with you, and nobody I know has written that part yet. Including me.",
  "Sovereignty as an itemized bill; the honest, self-implicating ending."),
 ("essay","dispatchesfromreality","essays/how-is-a-large-language-model-like-a-toaster/README.md","a cord",
  "A setting for every situation is not the same thing as knowing which situation this is. The one mercy the smart machine lacks: a cord. You can walk over, and unplug it, and it stops.",
  "Corrects his own opening with a meta-analysis that weakens it — 'dishonest to leave it out.'"),
 ("essay","dispatchesfromreality","lessons/cs-k12-the-scribe-who-forgot-his-dreams.md","the scribe",
  "The knowledge stayed. The days did not. He would help well tomorrow, too. He was sure of that also.",
  "A K-12 parable for stateless AI. The whole memory thesis, told with tenderness."),
 ("humor","dispatchesfromreality","creative/oakenscroll-french-toast.md","nana's french toast",
  "On the Structural Failure of Diner French Toast. Above 23 cubed, the toast holds itself together. It no longer needs you. This is the goal. Not dependency. Structural independence. Nana's French toast is better, because Nana has nowhere to be. And neither does the bread.",
  "A breakfast treatise that is secretly a manifesto about his own systems. Peer-reviewed by the syrup."),
 ("humor","willow-config","specs/oakenscroll_canon_full.json","codes like a poet",
  "Hanz: Codes like a poet. Cries like he means it. Gerald: headless rotisserie chicken, Acting Dean, communicates via single-word napkins at threshold crossings. Never early. Never late.",
  "UTETY faculty — 'the voices of the creator of Willow.'"),
 ("humor","aionic-claude-skills","skills/rober-rules/SKILL.md","the 10mm",
  "(Apocryphal) The 10mm socket is already gone.",
  "A mechanic's koan hidden in a coding skill."),
]
def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    n=0
    for theme,repo,source,title,quote,note in G:
        cur.execute("""INSERT INTO voices(repo,source,theme,title,quote,note) VALUES(%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (source,title) DO UPDATE SET theme=EXCLUDED.theme,quote=EXCLUDED.quote,note=EXCLUDED.note""",
                    (repo,source,theme,title,quote,note)); n+=1
    c.commit()
    cur.execute("SELECT theme,count(*) FROM voices GROUP BY theme ORDER BY 2 DESC")
    print(f"batch 2 seeded: {n}");
    for t,ct in cur.fetchall(): print(f"  {ct:>2} {t}")
    cur.execute("SELECT count(*) FROM voices"); print("total voices:",cur.fetchone()[0])
    cur.close(); c.close()
if __name__=="__main__": main()
