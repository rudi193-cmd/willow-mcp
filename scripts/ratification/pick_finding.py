import sqlite3, json
db = "/workspace/sean-data-vault/willow-store/research_20260714/store.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
cols = [r[1] for r in cur.execute('PRAGMA table_info("records")')]
print("verified findings (type=finding, verification_status=verified):\n")
for row in cur.execute('SELECT * FROM records'):
    d = dict(zip(cols, row))
    blob = d.get("data")
    try:
        j = json.loads(blob) if isinstance(blob, str) else blob
    except Exception:
        continue
    if isinstance(j, dict) and j.get("type") == "finding" and j.get("verification_status") == "verified":
        print("id:", d.get("id"))
        print("  statement:", (j.get("statement") or "")[:280])
        print("  source_doc:", j.get("source_doc"), "| domain:", j.get("domain"), "| tags:", j.get("tags"))
        print()
c.close()
