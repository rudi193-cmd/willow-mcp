import sqlite3, os, re, json
ROOT="/workspace/willow-live/store"
# find the newest timestamp anywhere in session-ish collections to date the snapshot
newest=[]
def ts_of(d):
    for k in ("updated_at","created_at","ts","timestamp","time"):
        v=d.get(k)
        if isinstance(v,str) and re.match(r'20\d\d-\d\d-\d\d', v): return v[:19]
    return None
for coll in sorted(os.listdir(ROOT)):
    db=os.path.join(ROOT,coll,"store.db")
    if not os.path.exists(db): continue
    try:
        c=sqlite3.connect(f"file:{db}?mode=ro",uri=True);cur=c.cursor()
        if not cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='records'").fetchone():
            c.close();continue
        cols=[r[1] for r in cur.execute('PRAGMA table_info("records")')]
        mx=None
        for row in cur.execute('SELECT * FROM records'):
            d=dict(zip(cols,row))
            try: j=json.loads(d.get("data","{}") or "{}")
            except: j={}
            merged=dict(d);
            if isinstance(j,dict): merged.update(j)
            t=ts_of(merged)
            if t and (mx is None or t>mx): mx=t
        c.close()
        if mx: newest.append((mx,coll))
    except Exception: pass
newest.sort(reverse=True)
print("Newest-record timestamp per collection (top 25):")
for t,c in newest[:25]:
    print(f"  {t}  {c}")
print("\nAbsolute newest record in the loaded live store:", newest[0] if newest else None)
