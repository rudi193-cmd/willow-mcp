#!/usr/bin/env python3
"""Curated factory toolkit: harvest tool files, dedup ACROSS names via file-level
MinHash (elementwise-min of member function fps = MinHash of the union), pick a
canonical source per tool, persist to `toolkit`. Re-runnable; excludes 'misc'.

A file is a TOOL if it has a main() / cli glue / lives in scripts|tools|bin|cli.
Curated core = every category except 'misc' (toggle with --all)."""
import re, sys, json, psycopg2
from collections import defaultdict

EXCLUDE_REPOS={"codebase-memory-mcp"}
INCLUDE_MISC = "--all" in sys.argv
MERGE_THRESH=0.65; BANDS=16
PRIORITY=["willow-mcp","willow-2.0","willow","kartikeya","willow-gate","jeles-remote",
          "openclaw-sap-gate","safe-app-willow-grove","safe-app-store","safe","corpus-lens","almanac-template"]
CATS=[("db/store",r"\b(db|store|soil|vault|sqlite|pg_|postgres|ledger)\b"),
 ("migration",r"migrat|_v1_v2|backfill|upgrade"),("validation",r"validat|check_|verify|lint|schema"),
 ("indexing",r"index|catalog|embed|corpus|search"),("monitoring",r"alert|links|recovery|rot|drift|outage|health|watch"),
 ("seed/scaffold",r"seed|scaffold|bootstrap|init|template|persona|compile"),
 ("extract/ingest",r"extract|ingest|scan|ocr|nest|intake|import"),
 ("worker/exec",r"worker|kart|sandbox|exec|queue|dispatch|task"),
 ("grove/comms",r"grove|channel|pigeon|message|mcp_|announce|reply"),
 ("auth/gate",r"oauth|opauth|auth|gate|sap|pgp|sign|identity|consent|egress"),
 ("cli/app",r"\b(cli|app|main|__main__|tui|serve|server)\b")]

def parse_fp(h):
    h=(h or "").strip()
    if len(h)<16: return None
    if len(h)%8: h=h.rjust((len(h)//8+1)*8,"0")
    return tuple(int(h[i:i+8],16) for i in range(0,len(h),8))
def cat(n,p):
    s=(n+" "+p).lower()
    for c,pat in CATS:
        if re.search(pat,s): return c
    return "misc"
def prio(r): return PRIORITY.index(r) if r in PRIORITY else len(PRIORITY)
def jac(a,b):
    k=min(len(a),len(b)); return sum(1 for i in range(k) if a[i]==b[i])/k if k else 0
class UF:
    def __init__(s): s.p={}
    def f(s,x):
        s.p.setdefault(x,x)
        while s.p[x]!=x: s.p[x]=s.p[s.p[x]]; x=s.p[x]
        return x
    def u(s,a,b): s.p[s.f(a)]=s.f(b)

def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    cur.execute("""SELECT repo, split_part(ref,':',1) file, label, body, n_lines, minhash, source_path
                   FROM pieces WHERE repo <> ALL(%s)""",(list(EXCLUDE_REPOS),))
    F=defaultdict(lambda:{"labels":set(),"lines":0,"cli":False,"fps":[],"path":""})
    for repo,file,label,body,nl,mh,sp in cur.fetchall():
        f=F[(repo,file)]; f["labels"].add(label); f["lines"]+=(nl or 0); f["path"]=sp or file
        if body and ("argparse" in body or "__main__" in body or "sys.argv" in body): f["cli"]=True
        fp=parse_fp(mh)
        if fp: f["fps"].append(fp)
    tools={}
    for (repo,file),f in F.items():
        is_tool=("main" in f["labels"]) or f["cli"] or bool(re.search(r"/(scripts|tools|bin|cli)/",(f["path"] or "").lower()))
        if not is_tool: continue
        base=re.sub(r"^.*/","",file)
        if not re.search(r"\.(py|js|ts|rs|sh|go|rb)$",base): continue
        category=cat(base,f["path"])
        if category=="misc" and not INCLUDE_MISC: continue
        if not f["fps"]:
            filefp=None
        else:
            k=min(len(x) for x in f["fps"]); filefp=tuple(min(x[i] for x in f["fps"]) for i in range(k))
        tools[(repo,file)]={"base":base,"repo":repo,"file":file,"lines":f["lines"],
                            "path":f["path"],"cat":category,"fp":filefp,"nfns":len(f["labels"])}
    # cross-name dedup via file-level MinHash LSH
    keys=[k for k in tools if tools[k]["fp"]]
    uf=UF()
    if keys:
        K=min(len(tools[k]["fp"]) for k in keys); rows=max(1,K//BANDS); buck=defaultdict(list)
        for k in keys:
            fp=tools[k]["fp"]
            for b in range(BANDS): buck[(b,fp[b*rows:(b+1)*rows])].append(k)
        for grp in buck.values():
            for i in range(len(grp)):
                for j in range(i+1,len(grp)):
                    if jac(tools[grp[i]]["fp"],tools[grp[j]]["fp"])>=MERGE_THRESH: uf.u(grp[i],grp[j])
    # also merge identical basenames (same tool, same name)
    byname=defaultdict(list)
    for k in tools: byname[tools[k]["base"]].append(k)
    for ks in byname.values():
        for k in ks[1:]: uf.u(ks[0],k)
    groups=defaultdict(list)
    for k in tools: groups[uf.f(k) if tools[k]["fp"] else k].append(k)

    cur.execute("""CREATE TABLE IF NOT EXISTS toolkit(
      id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY, tool text, category text,
      n_versions int, aliases text[], repos text[], canonical_repo text, canonical_path text,
      canonical_relpath text, canonical_lines int, replicated bool, created_at timestamptz DEFAULT now())""")
    cur.execute("TRUNCATE toolkit")
    catc=defaultdict(int); out=[]
    for members in groups.values():
        members.sort(key=lambda k:(prio(tools[k]["repo"]),-tools[k]["lines"]))
        canon=tools[members[0]]
        repos=sorted({tools[k]["repo"] for k in members})
        aliases=sorted({tools[k]["base"] for k in members})
        rel=re.sub(r"^/workspace/[^/]+/","",canon["path"]) if canon["path"] else canon["file"]
        catc[canon["cat"]]+=1
        cur.execute("""INSERT INTO toolkit(tool,category,n_versions,aliases,repos,canonical_repo,
                       canonical_path,canonical_relpath,canonical_lines,replicated)
                       VALUES(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (canon["base"],canon["cat"],len(members),aliases,repos,canon["repo"],
                     canon["path"],rel,canon["lines"],len(repos)>1))
        out.append((canon["cat"],canon["base"],len(repos),len(members),aliases,canon["repo"],rel))
    c.commit()
    print(f"curated tools (misc {'IN' if INCLUDE_MISC else 'OUT'}): {len(groups)}   from {len(tools)} tool-files\n")
    print("=== by category ===")
    for k,n in sorted(catc.items(),key=lambda x:-x[1]): print(f"  {n:>4}  {k}")
    print("\n=== cross-name MERGES (different filenames, same tool) ===")
    shown=0
    for cat_,base,nr,nv,aliases,repo,rel in sorted(out,key=lambda r:-len(r[4])):
        if len(aliases)>1:
            print(f"  {base:24} [{cat_}] aliases={aliases} canonical={repo}:{rel}"); shown+=1
        if shown>=15: break
    cur.close(); c.close()

if __name__=="__main__": main()
