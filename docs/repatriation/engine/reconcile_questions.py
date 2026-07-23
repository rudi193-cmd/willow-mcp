#!/usr/bin/env python3
"""Reconcile willow_compose.questions with the run persisted to willow's store
(question_runs/b8c77fcb). Writes ONLY to willow_compose (the apparatus DB;
WILLOW_PG_DB=willow is the protected one, untouched). Idempotent.

- 14 answered -> status='answered', answer=<concise verdict>
- 9 needs-gate -> status='held' (awaiting operator lifting the consent gate)
"""
import psycopg2

STORE_REF = "willow://store/question_runs/b8c77fcb (2026-07-18)"

ANSWERS = {
 15: "Honesty index: widest all-talk gap = Witnessed-seen (+2.09) but exonerated by the sessions leg (relational, not code-shaped). Real drift = Sovereignty (+1.08). Most honestly walked = Consent (smallest gap).",
 1:  "115/177 daemon/loop fns have no test naming them, but ~all are cbm C worker-pool threads tested higher up; heuristic under-counts. Genuine willow exposure: parent_watchdog_thread (the reaper).",
 2:  "exchange_authorization_code defined in 3 repos (grove->2.0->mcp lift). In willow-mcp: provider class + passing test but NO handle_callback consumer -> tested, not wired to a live callback route. Half-wired.",
 3:  "Top-5 most-rebuilt (12x) are almanac template scaffolding (expected). Most-rebuilt real tool = app.py (7x), then cli.py (6x).",
 4:  "'consent' appears 3x in essays vs 1531x in code (437 files). The loudest value is nearly silent in prose, overwhelming in implementation -- enacted, not preached.",
 5:  "Shortest voice = 'Care creates consciousness.' (27 chars), the central thesis. Terseness tracks authority -- the quietest line is load-bearing.",
 6:  "One clean self-correction surfaced: 'stay in the room... I got that half [wrong]'.",
 10: "Two code bodies quote essay lines verbatim as live strings: _run_install ('FRANK has reviewed the prerequisites'), jeles_stacks.py::main ('The things we think we've lost are simply...'). Prose compiled.",
 12: "Grove->hub lift proven at the byte: load_authorization_code content_sha 70a3864212 identical across grove+2.0+mcp; exchange_authorization_code identical across grove+2.0. Hash-verifiable, not name-inferred.",
 13: "leaves-become-soil: STATED richly ('maintaining the soil'-G.), ENACTED in the_grove.py (deep_roots, render_resting)+soil_graduate.py, but FLAGGED 06-02 'never consecrated: the nightly norn pass had almost certainly never completed a durable scheduled run.' Structure present, metabolism dormant.",
 16: "Lineage map built for all 7 convictions: belief->gate->ratifying session. Strongest ratification: Honest-gaps->cmd_gaps->'the honest gap decoded' (0.53). Weakest gate: Witnessed->test_no_self_directed_praise (0.25).",
 18: "Drift ranking (weakest code enforcement): Witnessed 0.25, Memory 0.40, Sovereignty 0.41 -- corroborates Q15 by a different method. Vindication: willow-mcp is the repo whose code sits closest to every conviction (0.78, least distant of 12). Lean hub = most value-dense.",
 21: "willow-mcp has 71 network-touching pieces, all named/honest: integrations.py adapters + oauth.py (Apple JWKS). No hidden cloud dependency. The leg the caching gap attaches to.",
 22: "Of willow-mcp's 619 fns, the 'no in-corpus caller' set is dominated by MCP tool entrypoints (called by protocol, invisible to structural test). Genuinely suspect: docs/design/*spike.py throwaways never deleted.",
}
NEEDS_GATE = [7, 8, 9, 11, 14, 17, 19, 20, 23]

def main():
    c = psycopg2.connect(dbname="willow_compose", user="root"); cur = c.cursor()
    # ensure a provenance column exists
    cur.execute("ALTER TABLE questions ADD COLUMN IF NOT EXISTS answered_via text")
    for qid, ans in ANSWERS.items():
        cur.execute("UPDATE questions SET status='answered', answer=%s, answered_via=%s WHERE id=%s",
                    (ans, STORE_REF, qid))
    cur.execute("UPDATE questions SET status='held' WHERE id = ANY(%s) AND status='open'", (NEEDS_GATE,))
    c.commit()
    cur.execute("SELECT status, count(*) FROM questions GROUP BY status ORDER BY 2 DESC")
    print("reconciled willow_compose.questions:")
    for s, n in cur.fetchall(): print(f"  {n:>2}  {s}")
    cur.execute("SELECT count(*) FROM questions WHERE answer IS NOT NULL")
    print(f"answers written: {cur.fetchone()[0]}")
    cur.execute("SELECT id, status FROM questions WHERE status='answered' ORDER BY id")
    print("answered ids:", ",".join(str(r[0]) for r in cur.fetchall()))
    cur.close(); c.close()

if __name__ == "__main__":
    main()
