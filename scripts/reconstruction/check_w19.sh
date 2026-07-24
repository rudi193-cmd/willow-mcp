#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
echo "[w19] knowledge columns:"
psql -d willow_19 -tAc "SELECT column_name||':'||data_type FROM information_schema.columns WHERE table_name='knowledge' ORDER BY ordinal_position" 2>&1
echo "[w19] knowledge rows: $(psql -d willow_19 -tAc 'SELECT count(*) FROM knowledge' 2>&1)"
echo "[w19] top domains:"
psql -d willow_19 -tAc "SELECT domain||' = '||count(*) FROM knowledge GROUP BY domain ORDER BY count(*) DESC LIMIT 15" 2>&1
