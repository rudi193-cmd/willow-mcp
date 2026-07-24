import sqlite3, json, subprocess, os, re
env = dict(os.environ, PGDATABASE="postgres")
def pg(q):
    return subprocess.run(["psql","-d","willow_both","-tAc",q],
                          capture_output=True, text=True, env=env).stdout.strip()

db = "/workspace/sean-data-vault/willow-store/research_20260714/store.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
cols = [r[1] for r in cur.execute('PRAGMA table_info("records")')]
findings = []
for row in cur.execute('SELECT * FROM records'):
    d = dict(zip(cols, row))
    try: j = json.loads(d["data"])
    except Exception: continue
    if isinstance(j, dict) and j.get("type")=="finding" and j.get("verification_status")=="verified":
        findings.append((d["id"], j))
c.close()

ABSENT, PRESENT = [], []
for fid, j in findings:
    if fid == "finding-not-a-computer-engineer":
        PRESENT.append((fid, "already sealed this session (65FC6835)")); continue
    stmt = j.get("statement","")
    m = re.search(r"-([0-9A-F]{8})$", fid)          # round2-*-<ATOMID>
    if m:
        hit = pg(f"SELECT count(*) FROM knowledge WHERE id='{m.group(1)}'")
        key = f"id={m.group(1)}"
    else:
        probe = stmt[15:70].replace("'", "''")
        hit = pg(f"SELECT count(*) FROM knowledge WHERE content ILIKE '%{probe}%'")
        key = "content-probe"
    (PRESENT if hit not in ("0","") else ABSENT).append((fid, j, key, hit))

print(f"=== ABSENT (to seal): {len(ABSENT)} ===")
for fid, j, key, hit in ABSENT:
    print(f"  {fid}  [{j.get('domain')}]  src={j.get('source_doc')}  ({key})")
    print(f"      {j.get('statement','')[:150]}")
print(f"\n=== PRESENT (skip, already reconciled): {len(PRESENT)} ===")
for item in PRESENT:
    print("  ", item[0], "::", item[2] if len(item)>2 else item[1], "hit="+item[3] if len(item)>3 else "")
