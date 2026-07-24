#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
echo "== top categories =="
psql -d willow_19 -F' | ' -tA -c "SELECT COALESCE(NULLIF(category,''),'(none)') c, count(*) n FROM knowledge GROUP BY c ORDER BY n DESC LIMIT 15"
echo; echo "== top projects =="
psql -d willow_19 -F' | ' -tA -c "SELECT COALESCE(NULLIF(project,''),'(none)') p, count(*) n FROM knowledge GROUP BY p ORDER BY n DESC LIMIT 15"
echo; echo "== source_types =="
psql -d willow_19 -F' | ' -tA -c "SELECT COALESCE(NULLIF(source_type,''),'(none)') s, count(*) n FROM knowledge GROUP BY s ORDER BY n DESC LIMIT 10"
