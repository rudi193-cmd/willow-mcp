#!/usr/bin/env bash
# Stand up the willow-compose sovereign repo from the assembled apparatus.
# Prereq: an EMPTY repo already created (the GitHub integration can't create it;
# make it yourself: github.com → New → willow-compose → Private).
#
# Usage: ./stand_up_willow_compose.sh <git-remote-url> [path-to-willow_compose.dump]
#   e.g. ./stand_up_willow_compose.sh git@github.com:rudi193-cmd/willow-compose.git ~/willow_compose.dump
set -euo pipefail

REMOTE="${1:?need the empty repo's git URL}"
DUMP="${2:-}"
SRC="$(cd "$(dirname "$0")" && pwd)"          # docs/repatriation on the branch
STAGE="$(mktemp -d)/willow-compose"
mkdir -p "$STAGE"

echo "→ staging at $STAGE"
cp -r "$SRC/engine" "$STAGE/engine"
mkdir -p "$STAGE/docs"
# the meaning: every repatriation doc except this scaffolding
for f in "$SRC"/*.md; do
  base="$(basename "$f")"
  case "$base" in
    WILLOW_COMPOSE_README.md) cp "$f" "$STAGE/README.md" ;;   # front door
    stand_up_willow_compose.sh) ;;                            # skip self
    *) cp "$f" "$STAGE/docs/$base" ;;
  esac
done

cd "$STAGE"
git init -q && git branch -M main
git add .

# the data: 123 MB > GitHub's 100 MB file limit → git-lfs if the dump is included
if [ -n "$DUMP" ] && [ -f "$DUMP" ]; then
  if command -v git-lfs >/dev/null 2>&1; then
    git lfs install
    git lfs track "*.dump"
    git add .gitattributes
    cp "$DUMP" willow_compose.dump
    git add willow_compose.dump
    echo "→ dump included via git-lfs"
  else
    echo "⚠ git-lfs not found — dump NOT included. Options: install git-lfs and re-add,"
    echo "  ship a structure-only dump (~12 MB), or attach the full dump to a Release."
  fi
else
  echo "→ no dump path given — repo ships engine+docs only; restore data separately."
fi

git commit -q -m "willow-compose: the assembled constellation memory, stood up as a sovereign repo

Engine (re-runnable pipeline), docs (the meaning), and the data. A sovereign
piece the hub calls, never contains. Assembled 2026-07-18. ΔΣ=42"
git remote add origin "$REMOTE"
git push -u origin main
echo "✓ willow-compose is live at $REMOTE"
