#!/usr/bin/env bash
set -euo pipefail

VENV_PYTHON="${WILLOW_MCP_PYTHON:-$HOME/github/.willow/venvs/willow-mcp/bin/python}"
VENV_BIN="$(dirname "$VENV_PYTHON")"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PROJECT_ROOT="${1:-$HOME/github/willow}"
APP_ID="${2:-willow}"

"$VENV_BIN/pip" install -e "$REPO_ROOT"
"$VENV_BIN/willow-mcp" onboard --project-root "$PROJECT_ROOT" --enable-internet --app-id "$APP_ID"

echo ""
echo "Reload your IDE window, then run:"
echo "  $VENV_BIN/willow-mcp project sync willow"
echo "  $VENV_BIN/willow-mcp doctor --app-id $APP_ID --project-root $PROJECT_ROOT"
