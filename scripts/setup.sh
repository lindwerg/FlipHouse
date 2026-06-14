#!/usr/bin/env bash
#
# Idempotent onboarding (P0 Шаг 0.12). Brings a fresh checkout to a runnable
# state: JS deps, Python venv + dev deps, Playwright browser, and the gitignored
# /vendor clones (re-cloning only the ones that are missing).
#
# Usage:
#   bash scripts/setup.sh            # do it
#   bash scripts/setup.sh --dry-run  # print the plan, change nothing

set -euo pipefail

cd "$(dirname "$0")/.."

DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then
  DRY_RUN=1
fi

run() {
  if [ "$DRY_RUN" = 1 ]; then
    echo "would: $*"
  else
    echo "+ $*"
    "$@"
  fi
}

echo "## 1. JS workspace deps"
run pnpm install --frozen-lockfile

echo "## 2. Python venv + dev deps"
if [ -d services/ai-worker-python/.venv ]; then
  echo "skip python venv (already present)"
else
  run python3 -m venv services/ai-worker-python/.venv
fi
run bash -c 'cd services/ai-worker-python && . .venv/bin/activate && pip install -U pip && pip install -r requirements-dev.txt'

echo "## 3. Playwright browser"
run pnpm --filter web exec playwright install chromium

echo "## 4. Vendor clones (idempotent — skip the ones already present)"
grep -v '^#' vendor/PINS.lock | grep -v '^[[:space:]]*$' | while IFS='|' read -r name url _rest; do
  name="$(echo "$name" | tr -d '[:space:]')"
  url="$(echo "$url" | tr -d '[:space:]')"
  [ -z "$name" ] && continue
  if [ -d "vendor/$name/.git" ]; then
    echo "skip $name (already present)"
  else
    run git clone --depth 1 "$url" "vendor/$name"
  fi
done

echo "## done"
