#!/usr/bin/env bash
#
# Single source of truth for the CI pipeline (P0 Шаг 0.11).
# Steps run in order under `set -e`, so the FIRST red step aborts the rest
# (fail-fast — a broken unit test never lets e2e or state-check run).
# .github/workflows/ci.yml calls THIS script, so CI and local stay identical.
#
# Each stage announces itself with `### STEP: <name>` so the order and the
# fail-fast behaviour are observable (see scripts/__tests__/ci-pipeline.test.mjs).

set -euo pipefail

cd "$(dirname "$0")/.."

echo "### STEP: lint"
pnpm lint

echo "### STEP: typecheck"
pnpm typecheck

echo "### STEP: node-tests"
# node:test meta-suites (workspace shape, state guard, vendor pins, ADR, CI).
# FLIPHOUSE_CI_LOCAL guards the ci-pipeline fail-fast test from recursing.
FLIPHOUSE_CI_LOCAL=1 node --test $(find scripts docs -name '*.test.mjs' | sort)

echo "### STEP: coverage"
pnpm coverage

echo "### STEP: pytest"
(
  cd services/ai-worker-python
  # shellcheck disable=SC1091
  . .venv/bin/activate
  ruff check .
  black --check .
  # `python -m pytest` (not bare `pytest`) so CWD is on sys.path and the
  # un-installed `fliphouse_worker` package imports.
  python -m pytest
)

echo "### STEP: e2e"
pnpm --filter web exec playwright test

echo "### STEP: state-check"
# Prefer the PR range (origin/main...HEAD); fall back to the last commit so a
# fully-pushed local tree still verifies the latest step touched STATE.md.
changed="$(git diff --name-only origin/main...HEAD 2>/dev/null || true)"
if [ -z "$changed" ]; then
  changed="$(git diff --name-only HEAD~1 HEAD 2>/dev/null || true)"
fi
CHANGED_FILES="$changed" bash scripts/check-state-updated.sh

echo "### STEP: done"
