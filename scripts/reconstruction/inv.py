import sqlite3, os, glob
root = "/workspace/vault-dbs"
KB_TABLES = {"knowledge","atoms","knowledge_atoms","entries","memories","facts","nodes","records"}
rows = []
for db in sorted(glob.glob(root + "/**/*.db", recursive=True)):
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        tot = 0; kb = ""
        for t in tabs:
            try:
                n = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]; tot += n
            except Exception: pass
        for t in tabs:
            if t.lower() in KB_TABLES:
                try:
                    cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{t}")')]
                    if any(x in [cc.lower() for cc in cols] for x in ("content","text","body","atom","fact")):
                        n = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                        kb += f"{t}={n} "
                except Exception: pass
        rows.append((os.path.relpath(db, root), len(tabs), tot, kb.strip()))
        c.close()
    except Exception as e:
        rows.append((os.path.relpath(db, root), -1, -1, f"ERR:{e}"))
rows.sort(key=lambda r: -r[2])
print(f"{'DB (relpath)':58} {'tab':>3} {'rows':>9}  kb-tables")
print("-"*100)
for r in rows:
    print(f"{r[0][:58]:58} {r[1]:>3} {r[2]:>9}  {r[3]}")
print("-"*100)
print(f"TOTAL: {len(rows)} dbs, {sum(r[2] for r in rows if r[2]>0):,} rows")
kbs = [r for r in rows if r[3]]
print(f"KB-bearing dbs: {len(kbs)}")
