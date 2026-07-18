#!/usr/bin/env python3
"""Read-only. Run the enact-axis over the 72 FOLD->mcp clusters.

For each cluster the matrix says 'FOLD to the hub, dedupe others in'. That is
only safe if the hub's canonical copy is the LIVE one. So for the canonical and
every member we ask: is it WIRED? (does a non-test piece in its OWN repo call
its label?). Then classify:

  CLEAN     canonical is wired -> fold is safe as written
  BACKWARDS canonical NOT wired but some member IS -> fold consolidates live code
            onto a dead hub copy (the OAuth failure mode). Canonical should flip.
  DEAD      nobody is wired -> structurally foldable but orphaned everywhere;
            do NOT fold into the value-dense hub (import-the-drift risk).

Caveat: 'wired' = same-repo, non-test caller mentioning the label. Short/common
labels (main, _resolve, reconcile) over-match; flagged AMBIG so verdicts on them
are soft, not trusted.
"""
import psycopg2, json

COMMON = {"main","run","__init__","_resolve","reconcile","setup","parse_args",
          "handle","execute","process","load","save","get","post","notice"}

c = psycopg2.connect(dbname="willow_compose", user="root"); cur = c.cursor()

def wired(repo, ref, label):
    """True if a non-test piece in the same repo (not this ref) calls the label."""
    if not label:
        return None
    cur.execute("""SELECT EXISTS(
        SELECT 1 FROM pieces
        WHERE repo=%s AND ref<>%s
          AND source_path NOT ILIKE '%%test%%' AND ref NOT ILIKE '%%test%%'
          AND body ILIKE '%%'||%s||'%%')""", (repo, ref, label))
    return cur.fetchone()[0]

cur.execute("""SELECT id, rep_name, canonical, members
               FROM component_clusters
               WHERE recommendation LIKE 'FOLD%mcp%' ORDER BY id""")
rows = cur.fetchall()

clean=[]; backwards=[]; dead=[]; unresolved=[]
for cid, rep_name, canonical, members in rows:
    # canonical = "willow-mcp:src/....py:142-174" -> repo, ref
    crepo, cref = canonical.split(":", 1)
    ambig = rep_name in COMMON or len(rep_name) < 5
    cwired = wired(crepo, cref, rep_name)
    # member liveness (exclude the canonical member itself)
    live_members = []
    for m in members:
        mrepo, mref, mname = m.get("repo"), m.get("ref"), m.get("name")
        if mrepo == crepo and mref == cref:
            continue
        if wired(mrepo, mref, mname):
            live_members.append(f"{mrepo}:{mname}")
    rec = dict(id=cid, name=rep_name, canonical=canonical, ambig=ambig,
               cwired=cwired, live_members=live_members)
    if cwired:
        clean.append(rec)
    elif live_members:
        backwards.append(rec)
    elif cwired is None:
        unresolved.append(rec)
    else:
        dead.append(rec)

print(f"72 FOLD->mcp clusters, enact-axis applied:\n")
print(f"  CLEAN     (canonical wired, fold safe): {len(clean)}")
print(f"  BACKWARDS (canonical dead, a member live): {len(backwards)}")
print(f"  DEAD      (orphaned everywhere): {len(dead)}")
print(f"  unresolved: {len(unresolved)}\n")

print("=== BACKWARDS — fold would consolidate live code onto a dead hub copy ===")
for r in sorted(backwards, key=lambda r: r["ambig"]):
    tag = " [AMBIG label]" if r["ambig"] else ""
    print(f"  #{r['id']} {r['name']}{tag}")
    print(f"      hub canonical (dead): {r['canonical']}")
    print(f"      live elsewhere:       {', '.join(r['live_members'])}")

print("\n=== DEAD — structurally foldable but called nowhere (do not fold; earn first) ===")
for r in sorted(dead, key=lambda r: r["ambig"]):
    tag = " [AMBIG]" if r["ambig"] else ""
    print(f"  #{r['id']} {r['name']}{tag}  <- {r['canonical']}")

cur.close(); c.close()
