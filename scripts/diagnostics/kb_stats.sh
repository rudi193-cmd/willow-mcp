#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
DB=willow_19
echo "== total atoms =="; psql -d $DB -tAc "SELECT count(*) FROM knowledge"
echo; echo "== DEDUP: identical titles appearing >1x (top 20) =="
psql -d $DB -F' | ' -tA -c "SELECT count(*) n, left(title,60) t FROM knowledge WHERE COALESCE(title,'')<>'' GROUP BY t HAVING count(*)>1 ORDER BY n DESC LIMIT 20"
echo; echo "== DEDUP magnitude: how many atoms are duplicate-title copies? =="
psql -d $DB -tAc "WITH d AS (SELECT title, count(*) c FROM knowledge WHERE COALESCE(title,'')<>'' GROUP BY title HAVING count(*)>1) SELECT 'dup_titles='||count(*)||'  redundant_copies='||COALESCE(sum(c-1),0) FROM d"
echo; echo "== SEAL/VERIFY column present in corpus? =="
psql -d $DB -tAc "SELECT string_agg(column_name,',') FROM information_schema.columns WHERE table_name='knowledge' AND (column_name ILIKE '%verif%' OR column_name ILIKE '%seal%' OR column_name ILIKE '%ratif%' OR column_name ILIKE '%confirm%')"
echo "  (empty above = the corpus stores NO verification/seal state)"
echo; echo "== thread term frequency (content::text ILIKE) =="
for term in translation reconcil "we do not guess" measure calibrat "translation memory" "sealed" "entity" "provenance" njord; do
  n=$(psql -d $DB -tAc "SELECT count(*) FROM knowledge WHERE content::text ILIKE '%$term%'")
  printf "   %-20s %s\n" "$term" "$n"
done
echo; echo "== visit-weighted: most-revisited atoms mentioning translation/reconcile/measure/seal =="
psql -d $DB -F' | ' -tA -c "SELECT visit_count, project, left(COALESCE(NULLIF(title,''),left(summary,50)),70) FROM knowledge WHERE content::text ILIKE ANY(ARRAY['%translation memory%','%reconcil%','%we do not guess%','%verified pair%','%sealed%']) ORDER BY visit_count DESC NULLS LAST LIMIT 15"
