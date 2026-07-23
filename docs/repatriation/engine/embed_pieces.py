#!/usr/bin/env python3
"""Embed willow_compose.pieces with the local CPU pipe (all-mpnet-base-v2, 768-dim)."""
import psycopg2, time
from sentence_transformers import SentenceTransformer
m=SentenceTransformer("sentence-transformers/all-mpnet-base-v2", device="cpu")
c=psycopg2.connect(dbname="willow_compose", user="root"); cur=c.cursor(); up=c.cursor()
cur.execute("SELECT id, coalesce(label,'')||' '||coalesce(ref,'')||' '||left(coalesce(body,''),400) "
            "FROM pieces WHERE embedding IS NULL")
rows=cur.fetchall()
print(f"to embed: {len(rows)}", flush=True)
t0=time.time(); done=0; B=256
for i in range(0,len(rows),B):
    chunk=rows[i:i+B]
    vecs=m.encode([r[1] for r in chunk], batch_size=64, show_progress_bar=False, normalize_embeddings=True)
    for (rid,_),v in zip(chunk,vecs):
        up.execute("UPDATE pieces SET embedding=%s WHERE id=%s",(list(map(float,v)),rid))
    c.commit(); done+=len(chunk)
    if i % (B*8)==0:
        print(f"  {done}/{len(rows)}  ({done/max(1,time.time()-t0):.0f}/s)", flush=True)
print(f"DONE pieces embedded: {done} in {time.time()-t0:.0f}s", flush=True)
cur.close(); up.close(); c.close()
