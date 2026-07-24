#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
echo "[fix] k0723 columns:"
psql -d willow_both -tAc "SELECT string_agg(column_name,',' ORDER BY ordinal_position) FROM information_schema.columns WHERE table_name='k0723'"
echo "[fix] rebuilding view with canonical 5 columns only..."
psql -d willow_both -q -c "DROP VIEW IF EXISTS knowledge;" 2>&1 | tail -1
psql -d willow_both -q -c "
CREATE VIEW knowledge AS
  SELECT id, content, domain, source, tags FROM k0723
  UNION ALL
  SELECT id,
         COALESCE(NULLIF(summary,''), NULLIF(title,''), content) AS content,
         COALESCE(NULLIF(category,''), NULLIF(project,'')) AS domain,
         source_type AS source,
         NULL::jsonb AS tags
  FROM k19;" 2>&1 | tail -2
echo "[fix] knowledge (union) = $(psql -d willow_both -tAc 'SELECT count(*) FROM knowledge')"
echo "[fix] sample corpus rows via the view:"
psql -d willow_both -tAc "SELECT id||' ['||COALESCE(domain,'?')||'] '||left(content,90) FROM knowledge WHERE content ILIKE '%willow%' LIMIT 3"
echo "[fix] DONE"
