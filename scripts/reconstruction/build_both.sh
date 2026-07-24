#!/usr/bin/env bash
# Build willow_both: a single DB whose `knowledge` relation UNIONs the curated
# willow_0723 KB (48 atoms) and the willow_19 corpus (229k), normalized to
# willow-mcp's canonical columns. No FDW — corpus rows are copied local for fast
# search. Aux tables (tasks/agents/routing_decisions/knowledge_edges) added empty
# so willow-mcp sees a complete schema.
set -uo pipefail
export PGDATABASE=postgres
LOG=/workspace/build_both_err.log; : > "$LOG"

dropdb willow_both 2>/dev/null || true
createdb willow_both && echo "[both] createdb ok"

# 1. curated 48-atom table -> k0723
pg_dump -d willow_0723 -t knowledge --no-owner 2>>"$LOG" | psql -d willow_both -q 2>>"$LOG"
psql -d willow_both -q -c "ALTER TABLE knowledge RENAME TO k0723;" 2>>"$LOG"

# 2. corpus -> local k19 (only the columns we need; drop embedding/jsonb-structure)
psql -d willow_both -q -c "CREATE TABLE k19 (id text, project text, title text, summary text, content text, source_type text, category text, created_at timestamptz);" 2>>"$LOG"
psql -d willow_19 -q -c "COPY (SELECT id, project, title, summary, content::text, source_type, category, created_at FROM knowledge) TO STDOUT WITH (FORMAT csv)" 2>>"$LOG" \
  | psql -d willow_both -q -c "COPY k19 FROM STDIN WITH (FORMAT csv)" 2>>"$LOG"

# 3. the union view, named `knowledge`, in willow-mcp canonical shape
psql -d willow_both -q -c "
CREATE VIEW knowledge AS
  SELECT id, content, domain, source, tags, created_at FROM k0723
  UNION ALL
  SELECT id,
         COALESCE(NULLIF(summary,''), NULLIF(title,''), content) AS content,
         COALESCE(NULLIF(category,''), NULLIF(project,'')) AS domain,
         source_type AS source,
         NULL::jsonb AS tags,
         created_at
  FROM k19;" 2>>"$LOG"

# 4. empty aux tables for a complete willow-mcp schema
pg_dump -d willow --schema-only -t tasks -t agents -t routing_decisions --no-owner 2>>"$LOG" | psql -d willow_both -q 2>>"$LOG"
pg_dump -d willow_vault --schema-only -t knowledge_edges --no-owner 2>>"$LOG" | psql -d willow_both -q 2>>"$LOG"

echo "[both] k0723 = $(psql -d willow_both -tAc 'SELECT count(*) FROM k0723')"
echo "[both] k19   = $(psql -d willow_both -tAc 'SELECT count(*) FROM k19')"
echo "[both] knowledge (union) = $(psql -d willow_both -tAc 'SELECT count(*) FROM knowledge')"
echo "[both] tables: $(psql -d willow_both -tAc "SELECT string_agg(tablename,',') FROM pg_tables WHERE schemaname='public'")"
echo "[both] err tail:"; tail -3 "$LOG"
echo "[both] DONE"
