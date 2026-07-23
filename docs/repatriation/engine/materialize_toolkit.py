#!/usr/bin/env python3
"""Materialize the curated `toolkit` rows into a clean tree:
  willow-toolkit/<category>/<tool>   (canonical source, from disk or raw.github)
plus MANIFEST.md and tools.json. Re-runnable."""
import os, re, json, subprocess, psycopg2
from pathlib import Path

OUT=Path("/workspace/willow-toolkit")
# repos still on disk (exact source)
DISK={"willow-mcp":"/home/user/willow-mcp","willow-2.0":"/workspace/willow-2.0",
      "kartikeya":"/workspace/kartikeya","willow-gate":"/workspace/willow-gate",
      "corpus-lens":"/workspace/corpus-lens","willow-data-vault":"/workspace/willow-data-vault",
      "sean-data-vault":"/workspace/sean-data-vault","willow":"/workspace/willow",
      "aionic-claude-skills":"/workspace/aionic-claude-skills","safe-app-willow-grove":"/workspace/safe-app-willow-grove",
      "willow-config":"/workspace/willow-config","willow-bot":"/workspace/willow-bot"}
def gh(repo):
    # (owner, name) for raw.githubusercontent
    if repo=="almanac-template": return ("almanac-data","almanac-template")
    if repo.startswith("almanac-"): return ("almanac-data", repo[len("almanac-"):])
    return ("rudi193-cmd", repo)

def fetch(repo, rel):
    # returns file text or None
    d=DISK.get(repo)
    if d:
        p=Path(d)/rel
        if p.is_file():
            try: return p.read_text(encoding="utf-8",errors="replace")
            except OSError: pass
    owner,name=gh(repo)
    for br in ("main","master"):
        url=f"https://raw.githubusercontent.com/{owner}/{name}/{br}/{rel}"
        if os.path.exists("/tmp/_tk"): os.remove("/tmp/_tk")
        r=subprocess.run(["curl","-sSL","--max-time","30","-w","%{http_code}","-o","/tmp/_tk",url],
                         capture_output=True,text=True)
        code=r.stdout.strip()[-3:]
        if code=="200" and os.path.exists("/tmp/_tk") and os.path.getsize("/tmp/_tk")>0:
            return Path("/tmp/_tk").read_text(encoding="utf-8",errors="replace")
    return None

def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    cur.execute("""SELECT tool,category,n_versions,aliases,repos,canonical_repo,canonical_relpath,canonical_lines,replicated
                   FROM toolkit ORDER BY category, replicated DESC, canonical_lines DESC""")
    rows=cur.fetchall()
    if OUT.exists(): subprocess.run(["rm","-rf",str(OUT)])
    OUT.mkdir(parents=True)
    got=miss=0; manifest=[]; used=set()
    for tool,category,nv,aliases,repos,crepo,crel,clines,repl in rows:
        catdir=OUT/re.sub(r"[^a-z0-9]+","-",category.lower())
        catdir.mkdir(exist_ok=True)
        text=fetch(crepo, crel)
        # unique filename within category
        fname=tool; base=fname
        i=1
        while (catdir/fname) in used:
            fname=f"{Path(base).stem}__{crepo}{Path(base).suffix}"; i+=1
            if i>3: fname=f"{Path(base).stem}__{crepo}_{i}{Path(base).suffix}"
        dest=catdir/fname
        status="ok"
        if text is None:
            miss+=1; status="MISSING(source not fetchable)"
            dest.write_text(f"# TOOL: {tool}\n# canonical: {crepo}/{crel}\n# source could not be re-fetched\n")
        else:
            got+=1; dest.write_text(text)
        used.add(catdir/fname)
        manifest.append({"tool":tool,"category":category,"file":str(dest.relative_to(OUT)),
                         "canonical":f"{crepo}/{crel}","versions":nv,"repos":repos,
                         "aliases":aliases,"replicated":repl,"lines":clines,"status":status})
    (OUT/"tools.json").write_text(json.dumps(manifest,indent=1))
    # MANIFEST.md
    from collections import defaultdict
    bycat=defaultdict(list)
    for m in manifest: bycat[m["category"]].append(m)
    md=["# willow factory toolkit","",
        f"Curated from a {sum(1 for _ in rows)}-tool harvest across 36 repos (willow_compose corpus).",
        f"Materialized {got} tools; {miss} unfetchable.","",
        "One canonical copy per distinct tool, deduped by name + file-level MinHash.","",
        "| category | tools |","|---|---|"]
    for cat in sorted(bycat): md.append(f"| {cat} | {len(bycat[cat])} |")
    md.append("")
    for cat in sorted(bycat):
        md.append(f"## {cat}")
        md.append("| tool | canonical source | copies | also-in |")
        md.append("|---|---|---|---|")
        for m in sorted(bycat[cat], key=lambda x:-x["versions"]):
            extra = "+".join(r for r in m["repos"] if r!=m["canonical"].split("/")[0])[:60]
            md.append(f"| `{m['file']}` | {m['canonical']} | {m['versions']} | {extra} |")
        md.append("")
    (OUT/"MANIFEST.md").write_text("\n".join(md))
    print(f"materialized: {got} ok, {miss} missing -> {OUT}")
    print("categories:", {k:len(v) for k,v in sorted(bycat.items())})
    cur.close(); c.close()

if __name__=="__main__": main()
