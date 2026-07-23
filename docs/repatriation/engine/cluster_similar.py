#!/usr/bin/env python3
"""Cluster near-duplicate pieces across the corpus using cbm's MinHash (fp).
LSH banding to find candidate pairs, exact MinHash-Jaccard to confirm, union-find
to cluster. Prints cross-repo clusters (the "I built this N times" signal)."""
import psycopg2
from collections import defaultdict

THRESH = 0.55        # Jaccard to call two pieces "same thing, different version"
BANDS = 16           # LSH bands

def parse_fp(hex_s):
    # cbm fp = concatenated 32-bit min values as 8-hex-char words
    hex_s = (hex_s or "").strip()
    if len(hex_s) < 16:
        return None
    if len(hex_s) % 8 != 0:                     # cbm drops the top word's leading zeros
        hex_s = hex_s.rjust((len(hex_s)//8 + 1) * 8, "0")
    return tuple(int(hex_s[i:i+8], 16) for i in range(0, len(hex_s), 8))

def jaccard(a, b):
    k = min(len(a), len(b))
    if k == 0: return 0.0
    return sum(1 for i in range(k) if a[i] == b[i]) / k

class UF:
    def __init__(self): self.p = {}
    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]; x = self.p[x]
        return x
    def union(self, a, b): self.p[self.find(a)] = self.find(b)

def main():
    conn = psycopg2.connect(dbname="willow_compose", user="root")
    cur = conn.cursor()
    cur.execute("SELECT id, repo, label, ref, minhash, n_lines FROM pieces "
                "WHERE minhash IS NOT NULL AND n_lines >= 5")
    items = {}
    for pid, repo, label, ref, mh, nlines in cur.fetchall():
        fp = parse_fp(mh)
        if fp: items[pid] = (repo, label, ref, fp)
    print(f"pieces with usable minhash (>=5 lines): {len(items)}")

    # LSH banding
    k = min(len(v[3]) for v in items.values())
    rows = max(1, k // BANDS)
    buckets = defaultdict(list)
    for pid, (_, _, _, fp) in items.items():
        for b in range(BANDS):
            band = fp[b*rows:(b+1)*rows]
            buckets[(b, band)].append(pid)

    # candidate pairs from shared buckets
    cand = set()
    for pids in buckets.values():
        if len(pids) < 2: continue
        for i in range(len(pids)):
            for j in range(i+1, len(pids)):
                cand.add((pids[i], pids[j]) if pids[i] < pids[j] else (pids[j], pids[i]))

    uf = UF()
    confirmed = 0
    for a, b in cand:
        if jaccard(items[a][3], items[b][3]) >= THRESH:
            uf.union(a, b); confirmed += 1
    print(f"candidate pairs: {len(cand)}   confirmed >= {THRESH}: {confirmed}")

    clusters = defaultdict(list)
    for pid in items:
        clusters[uf.find(pid)].append(pid)
    clusters = {r: m for r, m in clusters.items() if len(m) >= 2}

    xrepo = []
    for members in clusters.values():
        repos = {items[m][0] for m in members}
        if len(repos) >= 2:
            xrepo.append((len(members), len(repos), members))
    xrepo.sort(key=lambda t: (-t[1], -t[0]))
    print(f"\nclusters total: {len(clusters)}   cross-repo clusters: {len(xrepo)}\n")
    print("=== top cross-repo near-dupe clusters (same thing, many versions) ===")
    for n, nr, members in xrepo[:20]:
        by = defaultdict(list)
        for m in members: by[items[m][0]].append(items[m][2])
        name = items[members[0]][2].split("/")[-1]
        print(f"\n[{n} versions across {nr} repos]  e.g. {items[members[0]][1]} ~ {name}")
        for repo in sorted(by):
            print(f"    {repo:22} {by[repo][0]}" + (f"  (+{len(by[repo])-1} more)" if len(by[repo])>1 else ""))

if __name__ == "__main__":
    main()
