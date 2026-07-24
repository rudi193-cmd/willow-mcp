import sqlite3, glob, json, os
paths = []
for pat in ("/workspace/willow-live/store/*gaps*/store.db",
            "/workspace/sean-data-vault/willow-store/gaps/store.db",
            "/workspace/sean-data-vault/willow-store/research_20260714/store.db"):
    paths += glob.glob(pat)
def dump(db, limit=40):
    print(f"\n==== {db} ====")
    try:
        c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
        tabs = [r[0] for r in cur.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        for t in tabs:
            try:
                n = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{t}")')]
                print(f"  table {t}: {n} rows  cols={cols}")
            except Exception as e:
                print(f"  table {t}: ERR {e}")
        # dump the biggest data-bearing table
        best = None; bestn = -1
        for t in tabs:
            try:
                n = cur.execute(f'SELECT count(*) FROM "{t}"').fetchone()[0]
                if n > bestn and t != 'sqlite_sequence': bestn = n; best = t
            except: pass
        if best:
            cols = [r[1] for r in cur.execute(f'PRAGMA table_info("{best}")')]
            print(f"  --- {best} rows (up to {limit}) ---")
            for row in cur.execute(f'SELECT * FROM "{best}" LIMIT {limit}'):
                d = dict(zip(cols, row))
                blob = d.get('data') or d.get('value') or json.dumps(d)
                s = str(blob)
                if s.startswith('{'):
                    try:
                        j = json.loads(s)
                        s = ' | '.join(f"{k}={str(v)[:70]}" for k,v in j.items() if k not in ('embedding',))
                    except: pass
                print("   •", (d.get('id') or d.get('_id') or '?'), "::", s[:200])
        c.close()
    except Exception as e:
        print("  OPEN-ERR", e)
if not paths: print("no gap dbs found")
for p in sorted(set(paths)): dump(p)
