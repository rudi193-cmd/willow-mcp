#!/usr/bin/env bash
# SessionStart hook — make willow-mcp bootable as a native MCP server in
# Claude Code on the web.
#
# The stdio server is spawned by the client from .mcp.json; if its venv or
# $WILLOW_HOME aren't there yet, a missing import crashes it *before* the MCP
# handshake and the client just reports a reconnect failure (README documents
# this footgun). So this hook guarantees the prerequisites exist, and persists
# the env the server needs — computed per-host, so nothing host-specific has to
# live in the committed .mcp.json.
#
# Synchronous on purpose: the server must not spawn before its venv exists.
# Idempotent: safe to re-run; skips work that's already done (helps container
# caching). Web-only — local clones keep their own setup.
set -euo pipefail

if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

REPO="${CLAUDE_PROJECT_DIR:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
cd "$REPO"

# Env the stdio server needs, resolved for THIS host (portable: PG user comes
# from the actual OS user, paths from the repo root).
export WILLOW_HOME="$REPO/.willow"
export WILLOW_STORE_ROOT="$REPO/.willow/store"
export WILLOW_PG_DB="${WILLOW_PG_DB:-willow}"
export WILLOW_PG_USER="${WILLOW_PG_USER:-$(id -un)}"
export WILLOW_APP_ID="${WILLOW_APP_ID:-willow}"

# Best-effort: install bubblewrap. Kart sandboxes every task with `bwrap` for
# network isolation, so without it submitted tasks execute-fail instead of
# running. Non-fatal — the store/knowledge tools work regardless; only the task
# queue needs it.
if ! command -v bwrap >/dev/null 2>&1 && command -v apt-get >/dev/null 2>&1 \
     && command -v sudo >/dev/null 2>&1; then
  sudo apt-get install -y -q bubblewrap >&2 2>&1 || true
fi

# Best-effort: start a local Postgres cluster if one is installed but down.
# Postgres is optional (the SOIL store stands alone), so every step here is
# non-fatal — a failure just means knowledge_*/task_*/fleet_* degrade.
if command -v pg_lsclusters >/dev/null 2>&1 && command -v sudo >/dev/null 2>&1; then
  down_ver="$(pg_lsclusters 2>/dev/null | awk 'NR>1 && $4!="online"{print $1; exit}')"
  if [ -n "${down_ver:-}" ]; then
    sudo pg_ctlcluster "$down_ver" main start >&2 2>&1 || true
  fi
fi

# venv + editable install, scaffold $WILLOW_HOME, compile manifests, create the
# DB and apply docs/schema/*.sql — all through the one bootstrap implementation
# so there's no second copy to drift. WILLOW_PG_BOOTSTRAP_ROLE lets it create a
# Postgres role on a bare cluster. Progress goes to stderr; the hook's stdout
# stays clean.
WILLOW_PG_BOOTSTRAP_ROLE=1 bash "$REPO/scripts/sandbox-bootstrap.sh" >&2 || true

# The test suite needs pytest (bootstrap installs only runtime deps).
if [ -x "$REPO/.venv/bin/python3" ]; then
  "$REPO/.venv/bin/python3" -m pip install -q pytest >&2 2>&1 || true
fi

# .mcp.json is gitignored (it's local runtime config, not source), so a fresh
# clone has none for the client to load. Generate a minimal, env-free one — the
# env is supplied via $CLAUDE_ENV_FILE below, so this stays portable. Never
# clobber an existing file (you may have added your own servers/env).
if [ ! -f "$REPO/.mcp.json" ]; then
  cat > "$REPO/.mcp.json" <<'JSON'
{
  "mcpServers": {
    "willow-mcp": {
      "type": "stdio",
      "command": ".venv/bin/python3",
      "args": ["-m", "willow_mcp"]
    }
  }
}
JSON
fi

# Optional data-vault restore. If WILLOW_VAULT_RESTORE names an executable, run
# it and adopt any core WILLOW_* env it prints on stdout (KEY=VALUE per line) —
# WILLOW_HOME, WILLOW_STORE_ROOT, WILLOW_PG_DB, WILLOW_PG_USER, WILLOW_APP_ID.
# This is how a persistent data-vault (e.g. a cloned snapshot repo) supplies the
# real store, knowledge base, AND the identity to operate them as (e.g. an
# unscoped `operator` app that can see the restored collections) at session
# start — without hardcoding any personal vault in this agent-neutral hook. A
# pre-set WILLOW_APP_ID still wins if the vault doesn't declare one (the
# ${WILLOW_APP_ID:-willow} default above), so a purely-local identity works too.
# Runs after Postgres is up (the vault may load a dump); best-effort, non-fatal.
if [ -n "${WILLOW_VAULT_RESTORE:-}" ] && [ -x "${WILLOW_VAULT_RESTORE}" ]; then
  if _vault_env="$("${WILLOW_VAULT_RESTORE}" 2>>"$WILLOW_HOME/logs/vault-restore.log" || true)"; then
    while IFS='=' read -r _k _v; do
      case "$_k" in
        WILLOW_HOME|WILLOW_STORE_ROOT|WILLOW_PG_DB|WILLOW_PG_USER|WILLOW_APP_ID)
          [ -n "$_v" ] && export "$_k=$_v" ;;
      esac
    done <<< "$_vault_env"
  fi
fi

# Persist the env for the whole session so the client-spawned MCP server (and
# any shell you open) inherits it — this is why .mcp.json needs no env block.
if [ -n "${CLAUDE_ENV_FILE:-}" ]; then
  {
    echo "export WILLOW_HOME=\"$WILLOW_HOME\""
    echo "export WILLOW_STORE_ROOT=\"$WILLOW_STORE_ROOT\""
    echo "export WILLOW_PG_DB=\"$WILLOW_PG_DB\""
    echo "export WILLOW_PG_USER=\"$WILLOW_PG_USER\""
    echo "export WILLOW_APP_ID=\"$WILLOW_APP_ID\""
  } >> "$CLAUDE_ENV_FILE"
fi
