#!/usr/bin/env python3
"""Read-only. For kartikeya<->willow-2.0 diverged pieces: separate TRUE forks
(same code, decoupled) from LABEL COLLISIONS (same name, unrelated file), then
characterize the true forks' decoupling delta.

true fork  = line-set Jaccard >= 0.2 between the two bodies
collision  = < 0.2 (same identifier, different function)

For true forks: report line delta and which FLEET-COUPLING markers appear in the
willow-2.0 body but were stripped in kartikeya's (the decoupling), and vice versa.
"""
import psycopg2, re

FLEET = ["loop_heartbeat","fylgja","watchmen","SOIL","soil_client","norn",
         "human_required",".kart-scripts","kart-sandbox.json","worktree",
         "fleet","heartbeat","config.willow","willow.fylgja","sap.","from core",
         "from willow","from sap"]

c = psycopg2.connect(dbname="willow_compose", user="root"); cur = c.cursor()

def body(repo, label):
    cur.execute("""SELECT body FROM pieces WHERE repo=%s AND label=%s
                   ORDER BY n_lines DESC LIMIT 1""", (repo, label))
    r = cur.fetchone(); return r[0] if r else ""

def lineset(b):
    return set(l.strip() for l in b.splitlines() if l.strip())

# diverged pairs, both sides recognizably kart/fleet-execution code (exclude
# pyproject TOML keys and obvious unrelated files up front)
cur.execute("""
SELECT k.label, k.ref, w.ref, k.n_lines, w.n_lines FROM
 (SELECT DISTINCT ON (label) label,ref,n_lines,content_sha FROM pieces
   WHERE repo='kartikeya' AND length(label)>4 AND ref NOT ILIKE '%test%'
     AND ref ~ 'src/kartikeya/(sandbox|execute|queue|task_scan|lanes|pyenv|home|security_scan)'
   ORDER BY label,n_lines DESC) k
 JOIN
 (SELECT DISTINCT ON (label) label,ref,n_lines,content_sha FROM pieces
   WHERE repo='willow-2.0' AND length(label)>4 AND ref NOT ILIKE '%test%'
   ORDER BY label,n_lines DESC) w
 ON k.label=w.label
 WHERE k.content_sha <> w.content_sha
 ORDER BY k.label""")
pairs = cur.fetchall()

true_forks=[]; collisions=[]
for label, kref, wref, kn, wn in pairs:
    kb, wb = body('kartikeya', label), body('willow-2.0', label)
    ks, ws = lineset(kb), lineset(wb)
    inter = len(ks & ws); union = len(ks | ws) or 1
    jac = inter/union
    if jac >= 0.2:
        stripped = [m for m in FLEET if m.lower() in wb.lower() and m.lower() not in kb.lower()]
        added    = [m for m in FLEET if m.lower() in kb.lower() and m.lower() not in wb.lower()]
        true_forks.append((label, kn, wn, round(jac,2), kref, wref, stripped, added))
    else:
        collisions.append((label, round(jac,2), kref, wref))

print(f"kart diverged pairs examined: {len(pairs)}")
print(f"  TRUE FORKS (real decoupling): {len(true_forks)}")
print(f"  LABEL COLLISIONS (discard):   {len(collisions)}\n")

print("=== TRUE FORKS — the decoupling worklist ===")
print(f"{'piece':<32}{'kart':>5}{'w2.0':>6}{'jac':>6}  fleet coupling stripped in kartikeya")
for label,kn,wn,jac,kref,wref,stripped,added in sorted(true_forks, key=lambda x:-(x[2]-x[1])):
    delta = f"{kn}->{wn}" if kn!=wn else f"{kn}="
    mark = (", ".join(stripped)) if stripped else ("(same size, content diverged)" if kn==wn else "")
    print(f"{label:<32}{kn:>5}{wn:>6}{jac:>6.2f}  {mark[:60]}")

print("\n=== LABEL COLLISIONS discarded (same name, unrelated file) ===")
for label,jac,kref,wref in collisions:
    print(f"  {label:<28} jac={jac}  {kref.split('/')[-1]}  vs  {wref.split('/')[-1]}")
cur.close(); c.close()
