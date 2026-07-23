#!/usr/bin/env bash
# sandbox-bootstrap.sh — stand up willow-mcp in a local sandbox, idempotently.
#
# DEV-ONLY. This is the contributor sandbox, not the install. New users
# start from the charter seed (Willow/seed/seed.py — the six-movement
# onboarding); fleet operators use docs/OPERATOR-ONBOARD.md.
#
# One command to take a fresh clone to a working stdio MCP server:
#   bash scripts/sandbox-bootstrap.sh
#
# It does, in order (each step safe to re-run):
#   1. create .venv and `pip install -e .`         (skipped if the venv imports)
#   2. scaffold a repo-local $WILLOW_HOME (.willow) — gitignored sandbox state
#   3. compile the seeded fleet manifests
#   4. best-effort Postgres: create the DB if missing, apply docs/schema/*.sql
#      (SOIL store works without this; the knowledge base + task queue need it)
#   5. run diagnostic_summary over stdio and print the verdict
#
# Postgres is OPTIONAL and handled best-effort — if it isn't reachable the
# script says so and keeps going (the SOIL store is standalone). Knobs:
#   WILLOW_HOME        where to scaffold state        (default: <repo>/.willow)
#   WILLOW_PG_DB       database to use                (default: willow)
#   WILLOW_PG_USER     role to connect as             (default: $USER)
#   WILLOW_SKIP_PG=1   skip Postgres entirely (SOIL-only stand-up)
#   WILLOW_PG_BOOTSTRAP_ROLE=1
#                      also try to create a LOGIN SUPERUSER role named
#                      $WILLOW_PG_USER and the DB via `sudo -u postgres`, for a
#                      bare cluster where your OS user has no Postgres role yet
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

VENV="$REPO_ROOT/.venv"
PY="$VENV/bin/python3"
export WILLOW_HOME="${WILLOW_HOME:-$REPO_ROOT/.willow}"
export WILLOW_STORE_ROOT="${WILLOW_STORE_ROOT:-$WILLOW_HOME/store}"
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow}"
export WILLOW_PG_USER="${WILLOW_PG_USER:-${USER:-$(id -un)}}"

say() { printf '\n\033[1m== %s ==\033[0m\n' "$*"; }

# ── 1. venv + editable install ────────────────────────────────────────────────
say "venv + install"
if [ ! -x "$PY" ]; then
  python3 -m venv "$VENV"
fi
if ! "$PY" -c 'import willow_mcp' 2>/dev/null; then
  "$PY" -m pip install --upgrade pip -q
  "$PY" -m pip install -e . -q
  echo "installed willow-mcp (editable)"
elif ! "$PY" -m pip check >/dev/null 2>&1; then
  # #165: an already-importable venv can still be stale against pyproject's
  # pins — kartikeya 0.0.5 sat under a >=0.0.7 pin and left the worker
  # unstartable, and the fast path above never re-checked. `pip check` spots
  # the unsatisfied pin; re-sync instead of skipping.
  "$PY" -m pip install -e . -q
  echo "willow_mcp importable but pins unsatisfied — re-synced editable install"
else
  echo "willow_mcp already importable — skipping install"
fi

# ── 2. scaffold WILLOW_HOME ───────────────────────────────────────────────────
say "scaffold WILLOW_HOME ($WILLOW_HOME)"
"$VENV/bin/willow-mcp-init" >/dev/null
echo "home ready"

# ── 3. compile manifests ──────────────────────────────────────────────────────
say "compile manifests"
"$VENV/bin/willow-mcp-compile" --force >/dev/null
echo "manifests compiled"

# ── 4. Postgres (best-effort) ─────────────────────────────────────────────────
say "postgres (best-effort)"
if [ "${WILLOW_SKIP_PG:-0}" = "1" ]; then
  echo "WILLOW_SKIP_PG=1 — skipping; SOIL store stands alone"
elif ! command -v psql >/dev/null 2>&1; then
  echo "psql not found — skipping Postgres (knowledge_* / task_* / fleet_* will degrade)"
else
  if [ "${WILLOW_PG_BOOTSTRAP_ROLE:-0}" = "1" ] && command -v sudo >/dev/null 2>&1; then
    sudo -u postgres psql -tc "SELECT 1 FROM pg_roles WHERE rolname='$WILLOW_PG_USER'" 2>/dev/null | grep -q 1 \
      || sudo -u postgres psql -c "CREATE ROLE \"$WILLOW_PG_USER\" WITH LOGIN SUPERUSER;" 2>/dev/null || true
  fi
  # Ensure the database exists (createdb is a no-op error if it already does).
  if ! psql -U "$WILLOW_PG_USER" -d "$WILLOW_PG_DB" -c 'SELECT 1' >/dev/null 2>&1; then
    createdb -U "$WILLOW_PG_USER" "$WILLOW_PG_DB" 2>/dev/null \
      || sudo -u postgres createdb -O "$WILLOW_PG_USER" "$WILLOW_PG_DB" 2>/dev/null || true
  fi
  if psql -U "$WILLOW_PG_USER" -d "$WILLOW_PG_DB" -c 'SELECT 1' >/dev/null 2>&1; then
    for f in "$REPO_ROOT"/docs/schema/*.postgres.sql; do
      psql -U "$WILLOW_PG_USER" -d "$WILLOW_PG_DB" -v ON_ERROR_STOP=1 -f "$f" >/dev/null
      echo "applied $(basename "$f")"
    done
    echo "database '$WILLOW_PG_DB' ready"
    # Sandbox-only schema auto-confirm: unlocks task_* / knowledge writes on
    # the DDL this script itself just applied. Three guards inside (existing
    # artifacts untouched; every field exact@1.0; live columns == repo DDL) —
    # adopted/foreign schemas always fall through to the human confirm path.
    # See src/willow_mcp/sandbox_confirm.py.
    "$PY" -m willow_mcp.sandbox_confirm || true
  else
    echo "could not reach database '$WILLOW_PG_DB' as '$WILLOW_PG_USER' — skipping schema."
    echo "  (start your cluster, or re-run with WILLOW_PG_BOOTSTRAP_ROLE=1 on a bare cluster)"
  fi
fi

# ── 5. live self-check ────────────────────────────────────────────────────────
say "diagnostic_summary (live stdio handshake)"
WILLOW_APP_ID="${WILLOW_APP_ID:-willow}" "$PY" - <<'PY'
import json, os, subprocess, sys
env = dict(os.environ)
proc = subprocess.Popen([sys.executable, "-m", "willow_mcp"],
    stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    text=True, env=env, bufsize=1)
def send(o): proc.stdin.write(json.dumps(o) + "\n"); proc.stdin.flush()
def read():
    line = proc.stdout.readline()
    return json.loads(line) if line.strip() else None
send({"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "protocolVersion":"2025-06-18","capabilities":{},
    "clientInfo":{"name":"sandbox-bootstrap","version":"0"}}})
read()
send({"jsonrpc":"2.0","method":"notifications/initialized","params":{}})
send({"jsonrpc":"2.0","id":2,"method":"tools/call","params":{
    "name":"diagnostic_summary","arguments":{}}})
r = read().get("result", {})
d = json.loads("".join(c.get("text","") for c in r.get("content",[]) if c.get("type")=="text"))
print("verdict:", d.get("verdict"))
for name, chk in d.get("checks", {}).items():
    if isinstance(chk, dict) and "status" in chk:
        print(f"  {name:18} {chk['status']}")
for p in d.get("problems", []):
    print("  PROBLEM:", p.get("detail"))
proc.terminate()
sys.exit(0 if d.get("verdict") in ("ok", "degraded") else 1)
PY

cat <<EOF

Sandbox is up. To point an MCP client at it, use these env values:

  WILLOW_HOME=$WILLOW_HOME
  WILLOW_STORE_ROOT=$WILLOW_STORE_ROOT
  WILLOW_PG_DB=$WILLOW_PG_DB
  WILLOW_PG_USER=$WILLOW_PG_USER
  WILLOW_APP_ID=<the app whose manifest grants your tools>

Server command:  $PY -m willow_mcp
EOF
