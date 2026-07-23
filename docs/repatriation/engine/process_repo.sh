#!/usr/bin/env bash
# process_repo.sh <clone_url> <repo_name>
# Disk-safe: clone -> cbm index -> extract to pieces -> delete cbm project + clone.
# Idempotent: skips a repo already present in pieces.
set -u
CBM=/workspace/codebase-memory-mcp/build/c/codebase-memory-mcp
PY=/home/user/willow-mcp/.venv/bin/python
EX=/tmp/claude-0/-home-user-willow-mcp/e62e7dfd-17eb-5686-97cb-14a998884184/scratchpad/extract_pieces.py
url="$1"; name="$2"; dir="/workspace/$name"
export PGUSER=root

n=$(psql -d willow_compose -tAc "SELECT count(*) FROM pieces WHERE repo='$name'" 2>/dev/null)
if [ "${n:-0}" -gt 0 ]; then echo "SKIP $name (already $n pieces)"; exit 0; fi

[ -d "$dir" ] && rm -rf "$dir"
if ! git clone --depth 1 "$url" "$dir" >/tmp/clone_$name.log 2>&1; then
  echo "CLONE-FAIL $name"; tail -2 /tmp/clone_$name.log; exit 1
fi
"$CBM" cli index_repository "{\"repo_path\":\"$dir\"}" >/tmp/idx_$name.log 2>&1
proj="workspace-$name"
"$PY" "$EX" "$proj" "$dir" "$name" 2>&1 | tail -1
"$CBM" cli delete_project "{\"project\":\"$proj\"}" >/dev/null 2>&1
rm -rf "$dir"
echo "DONE $name  (disk now: $(df -h /workspace | awk 'NR==2{print $4}') free)"
