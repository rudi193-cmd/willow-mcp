#!/usr/bin/env bash
set -u
CBM=/workspace/codebase-memory-mcp/build/c/codebase-memory-mcp
PY=/home/user/willow-mcp/.venv/bin/python
EX=/tmp/claude-0/-home-user-willow-mcp/e62e7dfd-17eb-5686-97cb-14a998884184/scratchpad/extract_pieces.py
export PGUSER=root
REPOS="almanac-template climate-almanac health-almanac environment-almanac civic-almanac energy-almanac science-almanac transportation-almanac justice-almanac economy-almanac education-almanac agriculture-almanac"
PATHS="scripts/alert_on_dead_links.py scripts/alert_on_recovery_rot.py scripts/alert_on_revision_drift.py scripts/build_index.py scripts/check_links.py scripts/check_recovery_rot.py scripts/check_revision_drift.py scripts/migrate_v1_v2.py scripts/recovery_bot.py scripts/validate.py tests/__init__.py tests/test_catalog.py tests/test_recovery_rot.py tests/test_revision_drift.py"
for repo in $REPOS; do
  name="almanac-$repo"; [ "$repo" = "almanac-template" ] && name="almanac-template"
  n=$(psql -d willow_compose -tAc "SELECT count(*) FROM pieces WHERE repo='$name'" 2>/dev/null)
  if [ "${n:-0}" -gt 0 ]; then echo "SKIP $name ($n)"; continue; fi
  dir="/workspace/$name"; rm -rf "$dir"; got=0
  for br in main master; do
    for p in $PATHS; do
      mkdir -p "$dir/$(dirname "$p")"
      code=$(curl -sSL --max-time 30 -o "$dir/$p" -w "%{http_code}" "https://raw.githubusercontent.com/almanac-data/$repo/$br/$p" 2>/dev/null)
      if [ "$code" = "200" ] && [ -s "$dir/$p" ]; then got=$((got+1)); else rm -f "$dir/$p"; fi
    done
    [ $got -gt 0 ] && break
  done
  if [ $got -eq 0 ]; then echo "NOFILES $repo"; rm -rf "$dir"; continue; fi
  "$CBM" cli index_repository "{\"repo_path\":\"$dir\"}" >/tmp/idx_$name.log 2>&1
  "$PY" "$EX" "workspace-$name" "$dir" "$name" 2>&1 | tail -1
  "$CBM" cli delete_project "{\"project\":\"workspace-$name\"}" >/dev/null 2>&1
  rm -rf "$dir"
  echo "DONE $name ($got files)"
done
echo "=== ALMANAC GRAB COMPLETE ==="
psql -d willow_compose -tc "SELECT count(DISTINCT repo) repos, count(*) pieces FROM pieces WHERE repo LIKE 'almanac%';"
