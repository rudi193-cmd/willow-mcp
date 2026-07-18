#!/usr/bin/env python3
"""Extract Function/Method/Class symbols from a cbm-indexed project into
willow_compose.pieces, carrying cbm's MinHash fingerprint (fp) for cross-repo
similarity. Reads the symbol body from disk for content_sha (exact-dupe) and
storage. Durable: once in Postgres, the repo clone can be deleted.

Usage: extract_pieces.py <cbm_project> <repo_root> <repo_label>
"""
import hashlib, json, os, re, subprocess, sys
import psycopg2

CBM = "/workspace/codebase-memory-mcp/build/c/codebase-memory-mcp"

def cbm_query(project, cypher):
    out = subprocess.run([CBM, "cli", "query_graph",
                          json.dumps({"project": project, "query": cypher})],
                         capture_output=True, text=True)
    # cbm prints a log line then JSON; take the last JSON object
    txt = out.stdout.strip()
    start = txt.find("{", txt.rfind("\n") if "\n" in txt else 0)
    # robust: find first '{' of a line that parses
    for line in txt.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                return json.loads(line)
            except json.JSONDecodeError:
                continue
    return json.loads(txt)

_WS = re.compile(r"\s+")
_COMMENT = re.compile(r"#.*?$|//.*?$", re.MULTILINE)

def normalize(body: str) -> str:
    b = _COMMENT.sub("", body)
    b = _WS.sub(" ", b).strip()
    return b

def read_body(repo_root, file_path, s, e):
    fp = os.path.join(repo_root, file_path)
    try:
        with open(fp, "r", encoding="utf-8", errors="replace") as fh:
            lines = fh.readlines()
    except OSError:
        return ""
    s = max(1, int(s or 1)); e = int(e or s)
    return "".join(lines[s-1:e])

def main():
    project, repo_root, repo = sys.argv[1], sys.argv[2], sys.argv[3]
    conn = psycopg2.connect(dbname="willow_compose", user="root")
    cur = conn.cursor()
    total = 0
    for label in ("Function", "Method", "Class"):
        q = (f"MATCH (f:{label}) RETURN f.name, f.qualified_name, f.file_path, "
             f"f.start_line, f.end_line, f.signature, f.fp, f.sp, f.lines LIMIT 200000")
        res = cbm_query(project, q)
        for row in res.get("rows", []):
            name, fqn, fpath, s, e, sig, minhash, sp, nlines = (row + [None]*9)[:9]
            if not name or not fpath:
                continue
            body = read_body(repo_root, fpath, s, e)
            norm = normalize(body)
            csha = hashlib.sha256(norm.encode("utf-8", "replace")).hexdigest() if norm else None
            piece_key = f"{repo}:{fqn or (fpath + ':' + name)}:{s}"
            ref = f"{fpath}:{s}-{e}"
            meta = {"fqn": fqn, "signature": sig, "start": s, "end": e, "cbm_project": project}
            cur.execute("""
                INSERT INTO pieces (piece_key, repo, kind, ref, label, lang, body,
                                    source_path, meta, content_sha, minhash, struct_profile, n_lines)
                VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                ON CONFLICT (piece_key) DO UPDATE SET
                    content_sha=EXCLUDED.content_sha, minhash=EXCLUDED.minhash,
                    struct_profile=EXCLUDED.struct_profile, body=EXCLUDED.body,
                    meta=EXCLUDED.meta, n_lines=EXCLUDED.n_lines, updated_at=now()
            """, (piece_key, repo, label.lower(), ref, name,
                  os.path.splitext(fpath)[1].lstrip("."), body[:20000],
                  os.path.join(repo_root, fpath), json.dumps(meta),
                  csha, (minhash or None), (sp or None),
                  int(nlines) if str(nlines).isdigit() else None))
            total += 1
    conn.commit()
    cur.close(); conn.close()
    print(f"{repo}: upserted {total} pieces")

if __name__ == "__main__":
    main()
