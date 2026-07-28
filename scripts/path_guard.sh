#!/usr/bin/env bash
# path_guard.sh — Reject migration regressions in tracked code (CI).
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")/.."

if ! command -v rg >/dev/null 2>&1; then
  echo "path-guard: rg not installed — skip"
  exit 0
fi

fail=0

if rg -n '/home/[^/]+/willow-2\.0[^/]' \
    --glob '*.py' --glob '*.sh' --glob '*.json' \
    --glob '!tests/**' --glob '!docs/**' \
    --glob '!scripts/path_guard.sh' . 2>/dev/null; then
  echo "::error::Use env vars or github/willow, not bare willow-2.0 home paths"
  fail=1
fi

# The one check with a legitimate false positive: mcp_projects.py and
# project_wiring.py name this path in order to DROP a project entry that
# overrides WILLOW_STORE_ROOT to it — they enforce the same rule this guard
# does, and a substring match cannot tell a rejection from a use. A line
# carrying the `path-guard: allow` marker is exempt, which keeps the exemption
# at the line that earned it and next to the reason: any NEW occurrence still
# fails. Deliberately scoped to this check only — the other three have no such
# case, and a global escape hatch would weaken them for nothing.
store_hits="$(rg -n 'github/willow/\.willow/store' \
    --glob 'src/willow_mcp/deploy/**' \
    --glob 'src/willow_mcp/mcp_projects.py' \
    --glob 'src/willow_mcp/project_wiring.py' . 2>/dev/null \
    | grep -v 'path-guard: allow' || true)"
if [[ -n "${store_hits}" ]]; then
  echo "${store_hits}"
  echo "::error::Fleet SOIL is \$WILLOW_HOME/store — not github/willow/.willow/store"
  fail=1
fi

if rg -n 'fleet-fylgja-hook|fylgja-hook' \
    src/willow_mcp/deploy/ deploy/ 2>/dev/null; then
  echo "::error::Product deploy must use willow_mcp hooks, not fylgja fleet hooks"
  fail=1
fi

if rg -n '\$\{HOME\}/github/willow-2\.0' \
    --glob 'src/willow_mcp/deploy/**' \
    --glob 'src/willow_mcp/mcp_projects.py' \
    --glob 'src/willow_mcp/project_wiring.py' . 2>/dev/null; then
  echo "::error::Product project sync must not reference willow-2.0 paths"
  fail=1
fi

if [[ "${fail}" -eq 0 ]]; then
  echo "path-guard OK"
fi
exit "${fail}"
