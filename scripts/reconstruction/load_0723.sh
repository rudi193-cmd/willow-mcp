#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
V=/workspace/sean-data-vault
createdb willow_0723 2>/dev/null && echo "[load] createdb willow_0723 ok" || echo "[load] willow_0723 exists/failed"
sed -e '/^\\restrict/d' -e '/^\\unrestrict/d' "$V/postgres/willow-kb_2026-07-23_b329e17c.sql" \
  | psql -d willow_0723 -q -v ON_ERROR_STOP=0 2>/workspace/willow0723_err.log
echo "[load] knowledge count:"; psql -d willow_0723 -tAc "SELECT count(*) FROM knowledge" 2>&1
echo "[load] by domain:"; psql -d willow_0723 -tAc "SELECT domain, count(*) FROM knowledge GROUP BY 1 ORDER BY 2 DESC" 2>&1
echo "[load] err tail:"; tail -2 /workspace/willow0723_err.log 2>/dev/null
echo "[load] DONE"
