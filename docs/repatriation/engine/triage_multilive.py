#!/usr/bin/env python3
"""Read-only. Triage the non-kart MULTI-LIVE REVIEW forks by repo-family.

A MULTI-LIVE cluster is live (has a same-repo non-test caller) in >1 repo. The
kart family (kartikeya+willow-2.0) is handled elsewhere. Group the rest by the
SET of repos they're live in — forks travel in families, and the family dictates
the placement rule. For each family also measure identical-vs-diverged (by
content_sha across the pair) so 'pick one' vs 'real merge' is visible.
"""
import psycopg2
from collections import defaultdict

COMMON = {"main","run","__init__","_resolve","reconcile","setup","parse_args",
          "handle","execute","process","load","save","get","post","notice","_http_json",
          "_connect","_render","stats","mark_done","mark_running"}

c = psycopg2.connect(dbname="willow_compose", user="root"); cur = c.cursor()

def wired(repo, ref, label):
    if not label: return False
    cur.execute("""SELECT EXISTS(SELECT 1 FROM pieces WHERE repo=%s AND ref<>%s
        AND source_path NOT ILIKE '%%test%%' AND ref NOT ILIKE '%%test%%'
        AND body ILIKE '%%'||%s||'%%')""",(repo,ref,label))
    return cur.fetchone()[0]

def diverged(label):
    """across the piece's live repos: any content_sha mismatch for this label?"""
    cur.execute("""SELECT count(DISTINCT content_sha), count(DISTINCT repo)
                   FROM pieces WHERE label=%s AND length(label)>4""",(label,))
    shas, repos = cur.fetchone()
    return shas > 1

cur.execute("""SELECT id, rep_name, members FROM component_clusters
               WHERE recommendation LIKE 'REVIEW%' ORDER BY id""")
fam = defaultdict(list)
for cid, rep_name, members in cur.fetchall():
    live = set()
    for m in members:
        if wired(m.get("repo"), m.get("ref"), m.get("name")):
            live.add(m.get("repo"))
    if len(live) < 2:
        continue
    if live == {"kartikeya","willow-2.0"}:
        continue  # the kart family, handled in kart-productionization.md
    key = tuple(sorted(live))
    fam[key].append((rep_name, rep_name in COMMON, diverged(rep_name)))

total = sum(len(v) for v in fam.values())
print(f"non-kart MULTI-LIVE forks: {total}, in {len(fam)} repo-families\n")
print(f"{'n':>3} {'div':>4} {'hub?':>4}  repo-family  ::  sample pieces")
for key, items in sorted(fam.items(), key=lambda kv:-len(kv[1])):
    ndiv = sum(1 for _,_,d in items if d)
    hub = "HUB" if "willow-mcp" in key else ""
    samples = ", ".join(n for n,ambig,_ in items if not ambig)[:64]
    if not samples:
        samples = "("+", ".join(n for n,_,_ in items)[:56]+" — ambiguous names)"
    print(f"{len(items):>3} {ndiv:>3}d {hub:>4}  {'+'.join(key)}")
    print(f"              :: {samples}")
cur.close(); c.close()
