#!/usr/bin/env python3
"""Harvest the TOOLS (runnable utilities) across the corpus from willow_compose.pieces,
dedupe by name, pick a canonical source, categorize -> the factory toolkit blueprint.
Persists to a `toolkit` table and prints the manifest."""
import re, psycopg2
from collections import defaultdict

EXCLUDE_REPOS = {"codebase-memory-mcp"}
PRIORITY = ["willow-mcp","willow-2.0","willow","kartikeya","willow-gate","jeles-remote",
            "openclaw-sap-gate","safe-app-willow-grove","safe-app-store","safe","corpus-lens",
            "almanac-template"]
# category -> keyword patterns matched against tool name + path
CATS = [
    ("db/store",      r"\b(db|store|soil|vault|sqlite|pg_|postgres|ledger)\b"),
    ("migration",     r"migrat|_v1_v2|backfill|upgrade|alter"),
    ("validation",    r"validat|check_|verify|lint|schema"),
    ("indexing",      r"index|build_index|catalog|embed|corpus|search"),
    ("monitoring",    r"alert|check_links|recovery|rot|drift|outage|health|watch"),
    ("seed/scaffold", r"seed|scaffold|bootstrap|init|template|persona|compile"),
    ("extract/ingest",r"extract|ingest|scan|ocr|nest|intake|import"),
    ("worker/exec",   r"worker|kart|sandbox|exec|queue|dispatch|task"),
    ("grove/comms",   r"grove|channel|pigeon|message|mcp_|announce|reply"),
    ("auth/gate",     r"oauth|opauth|auth|gate|sap|pgp|sign|identity|consent|egress"),
    ("cli/app",       r"\b(cli|app|main|__main__|tui|serve|server)\b"),
]

def parse_fp(h):
    h=(h or "").strip()
    if len(h)<16: return None
    if len(h)%8: h=h.rjust((len(h)//8+1)*8,"0")
    return tuple(int(h[i:i+8],16) for i in range(0,len(h),8))

def categorize(name, path):
    s=(name+" "+path).lower()
    for cat,pat in CATS:
        if re.search(pat,s): return cat
    return "misc"

def prio(repo): return PRIORITY.index(repo) if repo in PRIORITY else len(PRIORITY)

def main():
    conn=psycopg2.connect(dbname="willow_compose",user="root"); cur=conn.cursor()
    cur.execute("""SELECT repo, split_part(ref,':',1) AS file, label, body, n_lines, minhash, source_path
                   FROM pieces WHERE repo <> ALL(%s)""",(list(EXCLUDE_REPOS),))
    files=defaultdict(lambda:{"labels":set(),"lines":0,"cli":False,"fps":[],"path":""})
    for repo,file,label,body,nlines,mh,spath in cur.fetchall():
        k=(repo,file); f=files[k]
        f["labels"].add(label); f["lines"]+=(nlines or 0); f["path"]=spath or file
        if body and ("argparse" in body or "__main__" in body or "sys.argv" in body): f["cli"]=True
        fp=parse_fp(mh)
        if fp: f["fps"].append(fp)
    # a file is a TOOL if it has a main() OR cli glue OR lives in a tool dir
    tools={}
    for (repo,file),f in files.items():
        is_tool = ("main" in f["labels"]) or f["cli"] or bool(re.search(r"/(scripts|tools|bin|cli)/", (f["path"] or "").lower()))
        if not is_tool: continue
        base=re.sub(r"^.*/","",file)
        if not base or not re.search(r"\.(py|js|ts|rs|sh|go|rb)$", base): continue
        tools[(repo,file)]={"base":base,"repo":repo,"file":file,"lines":f["lines"],
                            "path":f["path"],"cat":categorize(base,f["path"]),"nfns":len(f["labels"])}
    # group by basename -> a distinct tool
    bybase=defaultdict(list)
    for t in tools.values(): bybase[t["base"]].append(t)

    cur.execute("""CREATE TABLE IF NOT EXISTS toolkit(
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        tool text, category text, n_versions int, repos text[],
        canonical_repo text, canonical_path text, canonical_lines int,
        replicated bool, created_at timestamptz DEFAULT now())""")
    cur.execute("TRUNCATE toolkit")
    cat_counts=defaultdict(int); rows=[]
    for base,versions in bybase.items():
        versions.sort(key=lambda t:(prio(t["repo"]), -t["lines"]))
        canon=versions[0]
        repos=sorted({v["repo"] for v in versions})
        cat=canon["cat"]; cat_counts[cat]+=1
        cur.execute("""INSERT INTO toolkit(tool,category,n_versions,repos,canonical_repo,canonical_path,canonical_lines,replicated)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (base,cat,len(versions),repos,canon["repo"],canon["path"],canon["lines"],len(repos)>1))
        rows.append((cat,base,len(repos),len(versions),canon["repo"],canon["path"]))
    conn.commit()
    print(f"distinct tools: {len(bybase)}   (from {len(tools)} tool-file instances)\n")
    print("=== tools by category ===")
    for cat,n in sorted(cat_counts.items(), key=lambda x:-x[1]):
        print(f"  {n:>4}  {cat}")
    print("\n=== most-replicated tools (rebuilt across repos) ===")
    for cat,base,nr,nv,cr,cp in sorted(rows,key=lambda r:-r[2])[:22]:
        if nr<2: continue
        print(f"  [{nr} repos] {base:26} {cat:14} canonical: {cr}:{cp}")
    cur.close(); conn.close()

if __name__=="__main__": main()
