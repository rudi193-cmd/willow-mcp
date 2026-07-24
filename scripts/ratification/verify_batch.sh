#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
echo "k0723 rows now = $(psql -d willow_both -tAc 'SELECT count(*) FROM k0723')   (started at 48)"
echo "union rows now = $(psql -d willow_both -tAc 'SELECT count(*) FROM knowledge')   (started 229059)"
echo "reconciled-seal atoms in head = $(psql -d willow_both -tAc "SELECT count(*) FROM k0723 WHERE tags::text ILIKE '%reconciled-seal%'")"
echo "spot 'photographic negatives' = $(psql -d willow_both -tAc "SELECT count(*) FROM knowledge WHERE content ILIKE '%photographic negatives%'")"
echo "spot 'second-watershed'        = $(psql -d willow_both -tAc "SELECT count(*) FROM knowledge WHERE content ILIKE '%second-watershed%'")"
echo "spot 'OASST'                   = $(psql -d willow_both -tAc "SELECT count(*) FROM knowledge WHERE content ILIKE '%OASST%'")"
echo "dup check (any reconciled content appearing >1x in head?) = $(psql -d willow_both -tAc "SELECT COALESCE(sum(c-1),0) FROM (SELECT content, count(*) c FROM k0723 GROUP BY content HAVING count(*)>1) d")"
