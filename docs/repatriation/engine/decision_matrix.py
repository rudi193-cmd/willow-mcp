#!/usr/bin/env python3
"""Build the consolidation decision matrix from willow_compose.pieces.
Clusters non-test components across the corpus (cbm MinHash), picks a canonical
copy, attaches a recommendation, persists to component_clusters, prints a report."""
import json, psycopg2
from collections import defaultdict

THRESH = 0.6
BANDS = 16
EXCLUDE_REPOS = {"codebase-memory-mcp"}          # the tool itself
# priority for "which copy is canonical" — hub first, then fleet, then charter, then apps
PRIORITY = ["willow-mcp", "willow-2.0", "willow", "kartikeya", "willow-gate",
            "safe-app-willow-grove", "safe-app-store", "safe", "jeles-remote",
            "openclaw-sap-gate", "corpus-lens"]
GROVE = ("grove", "channel", "pigeon")
INFRA = ("db", "vault", "oauth", "embed", "sandbox", "cosine", "hash", "manifest", "ledger")

def parse_fp(h):
    h = (h or "").strip()
    if len(h) < 16: return None
    if len(h) % 8: h = h.rjust((len(h)//8+1)*8, "0")
    return tuple(int(h[i:i+8],16) for i in range(0,len(h),8))

def jac(a,b):
    k=min(len(a),len(b))
    return sum(1 for i in range(k) if a[i]==b[i])/k if k else 0.0

class UF:
    def __init__(self): self.p={}
    def find(self,x):
        self.p.setdefault(x,x)
        while self.p[x]!=x: self.p[x]=self.p[self.p[x]]; x=self.p[x]
        return x
    def union(self,a,b): self.p[self.find(a)]=self.find(b)

def prio(repo):
    return PRIORITY.index(repo) if repo in PRIORITY else len(PRIORITY)

def recommend(repos, name, ref):
    r = set(repos)
    key = (name + " " + ref).lower()
    if "willow-mcp" in r:
        return "FOLD→mcp (already in hub; dedupe others to import)"
    if any(g in key for g in GROVE):
        return "STANDALONE-LIB (Grove core; shared by apps → extract package)"
    if len(r) >= 3 and any(k in key for k in INFRA):
        return "STANDALONE-LIB (infra shared by many → extract package)"
    if r and all(x.startswith("safe") for x in r):
        return "APP-LOCAL (leave in SAFE apps)"
    return "REVIEW (decide fold vs standalone)"

def main():
    conn = psycopg2.connect(dbname="willow_compose", user="root"); cur = conn.cursor()
    cur.execute("""SELECT id, repo, label, ref, minhash FROM pieces
                   WHERE minhash IS NOT NULL AND n_lines >= 6
                     AND repo <> ALL(%s)
                     AND lower(coalesce(source_path,'')) NOT LIKE '%%test%%'
                     AND lower(ref) NOT LIKE '%%test%%'""", (list(EXCLUDE_REPOS),))
    items={}
    for pid,repo,label,ref,mh in cur.fetchall():
        fp=parse_fp(mh)
        if fp: items[pid]=(repo,label,ref,fp)
    print(f"non-test components with minhash: {len(items)}")
    k=min(len(v[3]) for v in items.values()); rows=max(1,k//BANDS)
    buckets=defaultdict(list)
    for pid,(_,_,_,fp) in items.items():
        for b in range(BANDS): buckets[(b,fp[b*rows:(b+1)*rows])].append(pid)
    cand=set()
    for pids in buckets.values():
        if len(pids)<2: continue
        for i in range(len(pids)):
            for j in range(i+1,len(pids)):
                cand.add((min(pids[i],pids[j]),max(pids[i],pids[j])))
    uf=UF()
    for a,b in cand:
        if jac(items[a][3],items[b][3])>=THRESH: uf.union(a,b)
    clusters=defaultdict(list)
    for pid in items: clusters[uf.find(pid)].append(pid)

    # persist
    cur.execute("""CREATE TABLE IF NOT EXISTS component_clusters(
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        rep_name text, n_versions int, n_repos int, repos text[],
        canonical text, recommendation text, members jsonb, created_at timestamptz DEFAULT now())""")
    cur.execute("TRUNCATE component_clusters")
    rowsout=[]
    for root,members in clusters.items():
        if len(members)<2: continue
        repos=sorted({items[m][0] for m in members})
        if len(repos)<2: continue                          # cross-repo only
        members_sorted=sorted(members, key=lambda m: prio(items[m][0]))
        canon=items[members_sorted[0]]
        rep_name=canon[1]
        rec=recommend(repos, rep_name, canon[2])
        mem=[{"repo":items[m][0],"name":items[m][1],"ref":items[m][2]} for m in members_sorted]
        cur.execute("""INSERT INTO component_clusters(rep_name,n_versions,n_repos,repos,canonical,recommendation,members)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)""",
                    (rep_name,len(members),len(repos),repos,
                     f"{canon[0]}:{canon[2]}",rec,json.dumps(mem)))
        rowsout.append((len(repos),len(members),rep_name,repos,f"{canon[0]}:{canon[2]}",rec))
    conn.commit()
    rowsout.sort(key=lambda t:(-t[0],-t[1]))
    print(f"cross-repo component clusters: {len(rowsout)}\n")
    print("RANK  repos  vers  component            recommendation")
    for nr,nv,name,repos,canon,rec in rowsout[:40]:
        print(f"  {nr:>2}   {nv:>3}   {name[:22]:22}  {rec}")
        print(f"            {'+'.join(repos)}")
        print(f"            canonical: {canon}")
    cur.close(); conn.close()

if __name__=="__main__":
    main()
