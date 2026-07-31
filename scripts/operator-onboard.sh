#!/usr/bin/env bash
set -euo pipefail

usage() {
    echo "Usage: WILLOW_MCP_PYTHON=/path/to/venv/bin/python $0 <project-root> <app-id>" >&2
    echo "" >&2
    echo "  WILLOW_MCP_PYTHON must point at the venv Python that has willow-mcp" >&2
    echo "  installed (see CONTRIBUTING.md's Development setup)." >&2
    exit 1
}

VENV_PYTHON="${WILLOW_MCP_PYTHON:-}"
PROJECT_ROOT="${1:-}"
APP_ID="${2:-}"
[ -n "$VENV_PYTHON" ] && [ -n "$PROJECT_ROOT" ] && [ -n "$APP_ID" ] || usage

VENV_BIN="$(dirname "$VENV_PYTHON")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

"$VENV_BIN/pip" install -e "$REPO_ROOT"
"$VENV_BIN/willow-mcp" onboard --project-root "$PROJECT_ROOT" --enable-internet --app-id "$APP_ID"

echo ""
echo "Reload your IDE window, then run:"
echo "  $VENV_BIN/willow-mcp project sync $APP_ID"
echo "  $VENV_BIN/willow-mcp doctor --app-id $APP_ID --project-root $PROJECT_ROOT"
