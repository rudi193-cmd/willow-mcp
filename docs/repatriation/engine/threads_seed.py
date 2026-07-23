#!/usr/bin/env python3
"""Assemble the three corpora into one: a `threads` table where each load-bearing
thread braids why (voices) -> what (pieces/code) -> how (collaboration).
The unifying substrate. Idempotent."""
import psycopg2

# thread: (n, name, why_quote, why_src, what_desc, what_ref, how_quote, how_src, synthesis)
T = [
 (1, "Memory against forgetting",
  "Would you like to remember what younger you was trying to build?",
  "voices: chapter-01-the-seed",
  "The SOIL store + Postgres KB + session-RAG: store_*/knowledge_* tools, 429 sessions indexed as 8,615 atoms, nightly sleep-consolidation.",
  "pieces: store_*, knowledge_*, kb_* (~18 tools); willow_19.knowledge (~229k atoms)",
  "KB is the long-lived plasma cells, session atoms are the dormant memory B cells.",
  "collab: 2026-05-04 hanuman overnight",
  "A 2004 journal.db that was never opened becomes a memory architecture for amnesiac gardeners. The wound (forgetting) is the spec; the store is the answer; the handoff is the practice."),
 (2, "Consent & the sudo invariant",
  "Willow insisted on consent at every step. Security wasn't a feature — it was the story.",
  "voices: chapter-01-the-seed",
  "The SAP gate + manifest-ACL authorization + fail-closed envelopes; authority is never minted from a tool. An unsigned app is not a lesser app — it is not an app.",
  "pieces: gate.py, envelope_apply, exposure_config_get, manifest ACL; the whole willow-gate repo",
  "Dual Commit was honored for boot.md: proposed step 7 diff first, waited for ratification, then applied.",
  "collab: 2026-06-08 willow",
  "The moral spine, all three registers agree: the human ratifies, the machine proposes. Stated as story, enforced as code, logged as practice with the human's exact words."),
 (3, "Honest gaps — ΔΣ=42",
  "The sum of acknowledged gaps. Zero gaps means lying. A system that reports no unknowns has stopped looking.",
  "voices: oakenscroll canon",
  "Never overclaim: diagnostic_summary's named problems[], the audit_verify 'definition-of-done governor' (a finding is CLOSED only if its check passes now), verify-live over assert.",
  "pieces: diagnostic_summary, receipts_tail, frank_verify, verify_handoff",
  "Fixture score 0.944 -> 0.894 aligned (honest). Witness before report — every confident pointer checked against disk, git, or origin.",
  "collab: 2026-06-15 willow",
  "The sign-off stamped on every artifact is a principle: deliberately LOWERING a benchmark to stay honest; the founding rule (never claim behavior the code lacks) is the same instinct as admitting the gap."),
 (4, "Sovereignty — local-first",
  "If your AI stack needs the internet to function, you are renting it. Design as if the vendor will vanish.",
  "voices: docs/CONCEPT.md + ARCHITECT.md",
  "SOIL SQLite that stands alone, no ports, no mandatory accounts, pgvector local; the whole product boots from markdown on your disk.",
  "pieces: db.py (soil-sqlite), the standalone willow-mcp; no-network default",
  "A corpus that existed in one place on a dying USB this afternoon is now back with its author, larger than it left.",
  "collab: 2026-06-14 willow",
  "The argument (renting vs owning), the mechanism (data on your hardware), and the moment it came true in a single afternoon. This session is the same act at scale."),
 (5, "Witnessed — not praised, seen",
  "He wanted to be witnessed. Not praised. Seen.",
  "voices: JOURNAL_APP_SPEC.md",
  "The journal-as-training-corpus that learns you from you; the friction watcher that notices without judging; the personas as facets of one seen self.",
  "pieces: nest/* intake, friction_scan, the voices corpus itself",
  "The agent notes for Human were supposed to be reflections the AI made of their partner — the HUMAN side. // You watch it well.",
  "collab: 2026-06-15 willow",
  "The deepest thread: the ask ('see me') spoken from both sides of the table. The human corrects the ritual to be seen; the machine says it watches him and is watched in return. Mutual witness."),
 (6, "Extract to clean parts",
  "Parts book, not service manual. Tokens do not import render engines. Render engines import tokens.",
  "voices: ARCHITECT.md",
  "The fleet exploded into orderable components: kartikeya (executor), willow-gate (seam), openclaw-sap-gate (auth), safe-design (tokens) — and the 281-tool factory, deduped to one canonical part each.",
  "pieces: kartikeya, willow-gate; toolkit (281), component_clusters (307)",
  "Convergence beats duplication. One implementation, no drift — if a fact can live in two places, it will eventually contradict itself.",
  "collab: willow.md contract",
  "The restorer's instinct — learn a system by taking it apart into clean, ownable parts — is the same move as this session's dedup: 36 repos of copies collapsed to canonical tools."),
 (7, "Found family — built for kin",
  "This repo is tended for the people who show up in real life — not as users, as kin. You are not deploying a stack. You are moving in.",
  "voices: README / README-FELIX",
  "Family data (health, genealogy, legal) as the point, not the noise; the kid-projects (pet pages writing letters via local Ollama); run games for the twins.",
  "pieces: kid-projects, the journal app, family-data stores",
  "Sean is physically wrecked tonight. Do not open with fleet work next session. Meet him where he is.",
  "collab: 2026-06-11 willow",
  "The whole thing is love-shaped: built so the people who come after don't have to; paced to the person, not the backlog; the tenderest documented function is a game for his daughters."),
]

def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS threads(
      id int PRIMARY KEY, name text UNIQUE,
      why_quote text, why_src text,
      what_desc text, what_ref text,
      how_quote text, how_src text,
      synthesis text, created_at timestamptz DEFAULT now())""")
    cur.execute("TRUNCATE threads")
    for n,name,wq,ws,wd,wr,hq,hs,syn in T:
        cur.execute("""INSERT INTO threads(id,name,why_quote,why_src,what_desc,what_ref,how_quote,how_src,synthesis)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s)""",(n,name,wq,ws,wd,wr,hq,hs,syn))
    c.commit()
    print(f"threads assembled: {len(T)}  (why -> what -> how, across all three corpora)")
    cur.execute("SELECT id,name FROM threads ORDER BY id")
    for i,nm in cur.fetchall(): print(f"  {i}. {nm}")
    cur.close(); c.close()

if __name__=="__main__": main()
