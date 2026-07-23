#!/usr/bin/env python3
"""Read-only. Run the enact-axis over the 180 REVIEW clusters.

For FOLD clusters the enact-axis CORRECTS. For REVIEW clusters — where the
matrix said 'structure can't decide' — it RESOLVES: whichever repo holds the
wired copy is the home.

Per cluster, for each member ask wired? (non-test same-repo caller of the label).
Then:
  RESOLVED->repo   exactly one repo has a live copy -> that repo is canonical
  MULTI-LIVE       >1 repo live -> genuinely human (both alive / maybe diverged)
  DEAD             nobody live -> defer; earn a consumer before placing

Same coarse caveat as the FOLD pass: wired = any same-repo caller (scaffolding
counts), so RESOLVED is a lean, not a proof; MULTI-LIVE and DEAD are the honest
'still needs a human' buckets.
"""
import psycopg2
from collections import Counter

COMMON = {"main","run","__init__","_resolve","reconcile","setup","parse_args",
          "handle","execute","process","load","save","get","post","notice","_http_json"}

c = psycopg2.connect(dbname="willow_compose", user="root"); cur = c.cursor()

def wired(repo, ref, label):
    if not label:
        return False
    cur.execute("""SELECT EXISTS(
        SELECT 1 FROM pieces
        WHERE repo=%s AND ref<>%s
          AND source_path NOT ILIKE '%%test%%' AND ref NOT ILIKE '%%test%%'
          AND body ILIKE '%%'||%s||'%%')""", (repo, ref, label))
    return cur.fetchone()[0]

cur.execute("""SELECT id, rep_name, members FROM component_clusters
               WHERE recommendation LIKE 'REVIEW%' ORDER BY id""")
rows = cur.fetchall()

resolved=[]; multi=[]; dead=[]
home_counter = Counter()
for cid, rep_name, members in rows:
    live_repos = set()
    for m in members:
        if wired(m.get("repo"), m.get("ref"), m.get("name")):
            live_repos.add(m.get("repo"))
    ambig = rep_name in COMMON or len(rep_name) < 5
    rec = dict(id=cid, name=rep_name, live=sorted(live_repos), ambig=ambig)
    if len(live_repos) == 1:
        home = next(iter(live_repos))
        rec["home"] = home
        resolved.append(rec)
        if not ambig:
            home_counter[home] += 1
    elif len(live_repos) > 1:
        multi.append(rec)
    else:
        dead.append(rec)

print(f"180 REVIEW clusters, enact-axis applied:\n")
print(f"  RESOLVED (one live repo -> canonical): {len(resolved)}")
print(f"  MULTI-LIVE (>1 live, still human):      {len(multi)}")
print(f"  DEAD (none live, defer):                {len(dead)}\n")

print("=== where RESOLVED clusters want to live (non-ambiguous labels) ===")
for repo, n in home_counter.most_common():
    print(f"  {n:>3}  -> {repo}")

print("\n=== sample RESOLVED->willow-mcp (fold to hub, now with a live reason) ===")
for r in [x for x in resolved if x.get("home")=="willow-mcp" and not x["ambig"]][:12]:
    print(f"  #{r['id']} {r['name']}")

print("\n=== MULTI-LIVE — genuinely needs a human (live in several places) ===")
for r in [x for x in multi if not x["ambig"]][:15]:
    print(f"  #{r['id']} {r['name']}  live in: {', '.join(r['live'])}")

print(f"\n(ambiguous-label clusters held soft: resolved={sum(1 for x in resolved if x['ambig'])}, "
      f"multi={sum(1 for x in multi if x['ambig'])}, dead={sum(1 for x in dead if x['ambig'])})")
cur.close(); c.close()
