# FlipHouse

Monorepo for FlipHouse — upload a long video, get ranked vertical clips with
native advertiser offers burned in, ready to publish.

> **Progress & process:** `STATE.md` is the single source of truth for what's
> done. Build rules: `docs/05-ПРОТОКОЛ-ВЫПОЛНЕНИЯ-И-ТЕСТЫ.md`. Phase plans:
> `roadmap/P0..P7`. Founder rule #1: **ZERO bugs** — every commit green, TDD first.

## Stack

- **pnpm workspace** (Node ≥ 24): `apps/web` (Next.js), `apps/worker-node`
  (BullMQ orchestrator), `services/ai-worker-python` (render pipeline),
  `packages/shared` (TS utilities).
- **Tooling:** TypeScript strict · ESLint flat + Prettier · Ruff + Black ·
  Vitest + Playwright + pytest · coverage gates that fail the build.
- **Upstream sources:** pinned in `/vendor` (`vendor/PINS.lock`), materialized
  by `scripts/setup.sh`.

## Quickstart

```bash
# 1. One-time onboarding (idempotent): JS deps, Python venv, Playwright, /vendor
bash scripts/setup.sh
#    preview without changing anything:
bash scripts/setup.sh --dry-run

# 2. Run the full local gate (same script CI runs)
bash scripts/ci-local.sh
```

## Common commands

```bash
pnpm lint            # ESLint over the workspace
pnpm typecheck       # tsc --noEmit
pnpm test            # all Vitest projects (packages/* + apps/*)
pnpm coverage        # Vitest + coverage thresholds (fails on shortfall)
pnpm --filter web test:e2e          # Playwright smoke (web)
node --test scripts/__tests__/*.test.mjs   # node:test meta-suites

# Python worker (run from its dir):
cd services/ai-worker-python && . .venv/bin/activate && python -m pytest
```

## Layout

```
apps/web                 Next.js App Router + /api/health + Playwright smoke
apps/worker-node         BullMQ queue resolver (orchestrator scaffold)
services/ai-worker-python  render-pipeline asserts (safe-zones, golden video)
packages/shared          content-hash / jobId helpers (@fliphouse/shared)
scripts/                 ci-local.sh (CI source of truth), setup.sh, guards
vendor/                  pinned upstream clones (git-ignored; PINS.lock tracked)
docs/, roadmap/, STATE.md
```

## CI

`.github/workflows/ci.yml` runs `scripts/ci-local.sh` on every PR and push to
`main`: lint → typecheck → node-tests → coverage → pytest → e2e → STATE.md guard,
fail-fast under `set -e`. The `ci` job is a required status check on `main`
(see `docs/ci/branch-protection.md`).
