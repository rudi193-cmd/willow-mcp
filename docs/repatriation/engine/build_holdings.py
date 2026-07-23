#!/usr/bin/env python3
"""Build/refresh the holdings registry: one durable, queryable row per data
holding in this box. PG sizes queried live; filesystem sizes via du. Re-runnable.
Also exports holdings.json + STARTUP.md for cold-session continuity."""
import json, os, subprocess, psycopg2
from pathlib import Path

def pg_db_size(db):
    try:
        c=psycopg2.connect(dbname="postgres",user="root"); cur=c.cursor()
        cur.execute("SELECT pg_size_pretty(pg_database_size(%s))",(db,)); s=cur.fetchone()[0]
        cur.close(); c.close(); return s
    except Exception: return None

def du(path):
    if not os.path.exists(path): return None
    r=subprocess.run(["du","-sh",path],capture_output=True,text=True)
    return r.stdout.split()[0] if r.stdout.strip() else None

# (kind, name, location, access, scope, summary)  size resolved below
ROWS=[
 ("service","postgresql-16","/var/lib/postgresql/16/main (unix socket)","psql -U root","infra","Postgres 16, socket-only (no TCP), serves all DBs; pgvector 0.6.0"),
 ("service","willow-mcp",".venv/bin/python3 -m willow_mcp (stdio)","mcp__willow-mcp__* tools","live","Product hub server; reads/writes willow_19 + willow-live/store"),
 ("service","codebase-memory-mcp","/workspace/codebase-memory-mcp/build/c/codebase-memory-mcp","cbm cli <tool> | MCP","tool","Code-graph indexer; graphs cached in /root/.cache/codebase-memory-mcp"),
 ("service","willow-2.0-sap_mcp","/workspace/willow-2.0 (venv .venv2)","mcpdrive stdio","dormant","Legacy fleet MCP; not persistently running (drive-test only)"),
 ("service","grove","remote MCP","OAuth (unavailable)","offline","Needs auth; not usable this session"),
 ("postgres","willow_19","pg db willow_19","psql -U root -d willow_19","live","PRODUCTION KB/fleet DB; knowledge ~229k atoms + messages/binder/opus/tasks"),
 ("postgres","willow_compose","pg db willow_compose","psql -d willow_compose","analysis","This session's corpus analysis: pieces, component_clusters, toolkit, holdings"),
 ("postgres","willow","pg db willow","psql -d willow","sandbox","Standalone willow-mcp schema; shell-env default, NOT what the server uses"),
 ("postgres","willow_vault","pg db willow_vault","psql -d willow_vault","snapshot","Vault snapshot (knowledge/tasks/edges)"),
 ("postgres","willow_vault_jul16","pg db willow_vault_jul16","psql","snapshot","Older vault snapshot (Jul 16)"),
 ("postgres","willow_ci","pg db willow_ci","psql","test","CI test DB"),
 ("postgres","corpuslens_test","pg db corpuslens_test_809897e3","psql","test","corpus-lens test DB"),
 ("soil","willow-live-store","/workspace/willow-live/store","via willow-mcp server (WILLOW_STORE_ROOT)","live","LIVE SOIL store, 107 collections (agents_*, gaps, handoffs, lineage, cube_cells)"),
 ("soil","willow-mcp-sandbox-store","/home/user/willow-mcp/.willow/store","store_* MCP tools","sandbox","Repo-local gitignored SOIL store"),
 ("soil","vault-restore","/workspace/vault-restore/.willow/store","filesystem","snapshot","Restored vault snapshot + inspect-home/"),
 ("kb","willow_19.knowledge","willow_19.public.knowledge","knowledge_search / kb_at","live","Primary KB — ~229k atoms, ~1.2GB"),
 ("kb","willow_19.opus_atoms","willow_19.public.opus_atoms","psql","live","Opus-tier knowledge sub-store"),
 ("kb","willow_compose.pieces","willow_compose.public.pieces","psql / engine scripts","analysis","29,432 code symbols + cbm MinHash across 36 repos"),
 ("cbm","code-graph-cache","/root/.cache/codebase-memory-mcp","cbm cli query_graph/search_graph","tool","8 project code-graphs cached (rest deletable/re-indexable in seconds)"),
 ("ledger","frank-receipts","/home/user/willow-mcp/.willow/{mcp_receipt.db,ledgers,.kart-logs}","frank_* MCP / receipts_tail","live","Tool receipts + FRANK ledger + Kart logs"),
 ("vault","local-vault","/home/user/willow-mcp/.willow/vault.db (+vault.key)","encrypted vault","live","Encrypted local secret vault"),
 ("toolkit","willow-toolkit","/workspace/willow-toolkit (+ .tar.gz)","filesystem","analysis","281 curated canonical tools, 11 categories"),
 ("table","component_clusters","willow_compose.public.component_clusters","psql","analysis","307 cross-repo consolidation decisions (fold/standalone/delete)"),
 ("table","toolkit","willow_compose.public.toolkit","psql","analysis","281-tool catalog: canonical source, category, dedup"),
 ("repos","source-clones","/workspace/* + /home/user/willow-mcp","git","source","Repo clones on disk (sean-data-vault 4.5G, cbm 1.8G, willow 466M, willow-2.0 308M, +12)"),
]

def resolve_size(kind,name,location):
    if kind in ("postgres","kb") and name.split(".")[0] in ("willow_19","willow","willow_vault","willow_vault_jul16","willow_ci","willow_compose"):
        return pg_db_size(name.split(".")[0]) or ""
    if location.startswith("/") :
        p=location.split(" ")[0]
        return du(p) or ""
    return ""

def main():
    c=psycopg2.connect(dbname="willow_compose",user="root"); cur=c.cursor()
    cur.execute("""CREATE TABLE IF NOT EXISTS holdings(
        id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
        name text UNIQUE, kind text, location text, access_method text,
        scope text, size text, summary text, refreshed_at timestamptz DEFAULT now())""")
    cur.execute("TRUNCATE holdings")
    export=[]
    for kind,name,loc,acc,scope,summ in ROWS:
        size=resolve_size(kind,name,loc)
        cur.execute("""INSERT INTO holdings(name,kind,location,access_method,scope,size,summary)
                       VALUES(%s,%s,%s,%s,%s,%s,%s)""",(name,kind,loc,acc,scope,size,summ))
        export.append({"name":name,"kind":kind,"location":loc,"access":acc,"scope":scope,"size":size,"summary":summ})
    c.commit()
    # continuity exports
    outdir=Path("/workspace/willow-toolkit"); outdir.mkdir(exist_ok=True)
    (outdir/"holdings.json").write_text(json.dumps(export,indent=1))
    md=["# STARTUP — box holdings map (cold-session continuity)","",
        "Query live: `psql -U root -d willow_compose -c 'SELECT kind,name,scope,size,location FROM holdings ORDER BY kind,name'`","",
        "| kind | name | scope | size | access |","|---|---|---|---|---|"]
    for h in export:
        md.append(f"| {h['kind']} | {h['name']} | {h['scope']} | {h['size']} | {h['access']} |")
    md += ["","## Load-bearing (don't lose)",
        "- **willow_19** (Postgres) — production KB, ~229k atoms. Live server writes here.",
        "- **/workspace/willow-live/store** — live SOIL, 107 collections.",
        "- **willow_compose** — this analysis (pieces/clusters/toolkit/holdings).",
        "","## Gotcha","Shell env → sandbox (`willow` db, `.willow/store`). The running server → live (`willow_19`, `willow-live/store`). Raw psql hits the sandbox."]
    (outdir/"STARTUP.md").write_text("\n".join(md))
    print(f"holdings registry: {len(export)} rows")
    cur.execute("SELECT kind, count(*) FROM holdings GROUP BY kind ORDER BY 2 DESC")
    for k,n in cur.fetchall(): print(f"  {n:>2}  {k}")
    cur.close(); c.close()

if __name__=="__main__": main()
