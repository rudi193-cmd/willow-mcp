import sqlite3, glob, os
root = "/workspace/vault-dbs"
targets = [
    "windows-era-willow-kb/archive/windows-extract/willow-kb/willow_knowledge.db",
    "willow-root-meta/.willow/willow-2.0.db",
]
# also find any db under willow-root-meta
for db in glob.glob(root + "/willow-root-meta/**/*.db", recursive=True):
    rel = os.path.relpath(db, root)
    if rel not in targets: targets.append(rel)

for rel in targets:
    db = os.path.join(root, rel)
    if not os.path.exists(db):
        print(f"### MISSING: {rel}\n"); continue
    print(f"### {rel}   ({os.path.getsize(db)//1024} KB)")
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
        for t in [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]:
            try:
                n = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{t}")')]
                print(f"   {t:32} {n:>8}  [{', '.join(cols[:8])}]")
            except Exception as e:
                print(f"   {t:32}  ERR {e}")
        c.close()
    except Exception as e:
        print(f"   OPEN-ERR {e}")
    print()
