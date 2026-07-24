#!/usr/bin/env bash
set -uo pipefail
export PGDATABASE=postgres
echo "seal landed in writable head k0723?  $(psql -d willow_both -tAc "SELECT id||' <'||domain||'>' FROM k0723 WHERE id='65FC6835'")"
echo "k0723 rows now = $(psql -d willow_both -tAc 'SELECT count(*) FROM k0723')  (was 48)"
echo "union rows now = $(psql -d willow_both -tAc 'SELECT count(*) FROM knowledge')  (was 229059)"
echo "not in the raw corpus k19 (stayed stranded there)?  k19 hits = $(psql -d willow_both -tAc "SELECT count(*) FROM k19 WHERE id='65FC6835'")"
