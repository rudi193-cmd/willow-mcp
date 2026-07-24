#!/usr/bin/env bash
# Load the willow_19 full-corpus Postgres dump into a fresh DB, with pgvector.
set -uo pipefail
export PGDATABASE=postgres
V=/workspace/sean-data-vault/postgres
echo "[load] installing pgvector"
sudo apt-get install -y -q postgresql-16-pgvector >/dev/null 2>&1 && echo "[load] pgvector installed" || echo "[load] pgvector install FAILED (continuing)"
createdb willow_19 2>/dev/null && echo "[load] createdb willow_19 ok" || echo "[load] willow_19 exists/failed"
psql -d willow_19 -q -c "CREATE EXTENSION IF NOT EXISTS vector" 2>&1 | tail -2
echo "[load] streaming 675MB dump (this takes a few minutes)..."
cat "$V"/willow_19_dump.sql.gz.part-* | zcat \
  | sed -e '/^\\restrict/d' -e '/^\\unrestrict/d' \
  | psql -d willow_19 -q -v ON_ERROR_STOP=0 >/dev/null 2>/workspace/willow19_err.log
echo "[load] done. table row counts:"
psql -d willow_19 -tAc "SELECT relname||' = '||n_live_tup FROM pg_stat_user_tables ORDER BY n_live_tup DESC LIMIT 20" 2>&1
echo "[load] knowledge count:"
psql -d willow_19 -tAc "SELECT count(*) FROM knowledge" 2>&1
echo "[load] error tail:"; tail -3 /workspace/willow19_err.log 2>/dev/null
echo "[load] COMPLETE"
