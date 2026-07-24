import sqlite3, json, re
db = "/workspace/sean-data-vault/willow-store/research_20260714/store.db"
c = sqlite3.connect(f"file:{db}?mode=ro", uri=True); cur = c.cursor()
cols = [r[1] for r in cur.execute('PRAGMA table_info("records")')]
out = []
for row in cur.execute('SELECT * FROM records'):
    d = dict(zip(cols, row))
    try: j = json.loads(d["data"])
    except Exception: continue
    if not (isinstance(j, dict) and j.get("type")=="finding" and j.get("verification_status")=="verified"):
        continue
    if d["id"] == "finding-not-a-computer-engineer":
        continue
    m = re.search(r"-([0-9A-F]{8})$", d["id"])
    atom_id = m.group(1) if m else None
    src_doc = j.get("source_doc","")
    src = (f"SOIL research_20260714/{d['id']} (verification_status=verified"
           + (f"; canonical atom {atom_id}" if atom_id else "")
           + f"; source_doc={src_doc}). Reconciled SOIL->Postgres by the willow seat, "
             "session evening-chat-i5i6tr, under operator-granted standing write "
             "(lineage: grant-standing-write-evening-chat-i5i6tr), 2026-07-24. "
             "Batch reconciliation of verified findings; split-brain docs/the-nestor-lineage.md §4.2.")
    tags = ["finding","verified", j.get("domain","operator-model"), "reconciled-seal","2026-07-24"]
    if src_doc: tags.append(src_doc)
    out.append({"fid": d["id"], "domain": j.get("domain","operator-model"),
                "statement": j.get("statement",""), "source": src, "tags": tags})
c.close()
json.dump(out, open("/workspace/seals.json","w"), indent=1, ensure_ascii=False)
print(f"wrote {len(out)} seals to /workspace/seals.json")
for i,s in enumerate(out):
    print(f"\n[{i}] {s['fid']}  <{s['domain']}>")
    print("   content:", s["statement"])
