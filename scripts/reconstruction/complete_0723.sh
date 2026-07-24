#!/usr/bin/env bash
# Give willow_0723 the full willow-mcp table set (aux tables empty), keeping its
# fresh 48-atom knowledge table. Aux schema copied from the canonical `willow`
# DB; knowledge_edges from willow_vault.
set -uo pipefail
export PGDATABASE=postgres
pg_dump -d willow --schema-only -t tasks -t agents -t routing_decisions 2>/dev/null \
  | psql -d willow_0723 -q -v ON_ERROR_STOP=0 2>>/workspace/complete0723_err.log
pg_dump -d willow_vault --schema-only -t knowledge_edges 2>/dev/null \
  | psql -d willow_0723 -q -v ON_ERROR_STOP=0 2>>/workspace/complete0723_err.log
echo "[0723] tables now present:"
psql -d willow_0723 -tAc "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1" 2>&1 | tr '\n' ' '
echo; echo "[0723] knowledge count: $(psql -d willow_0723 -tAc 'SELECT count(*) FROM knowledge' 2>&1)"
echo "[0723] DONE"
