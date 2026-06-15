# `web` — FlipHouse product shell

Next.js 16 (App Router) + Clerk auth + organizations + Drizzle/Postgres.

## Source / attribution

Forked from **[ixartz/SaaS-Boilerplate](https://github.com/ixartz/SaaS-Boilerplate)**
(MIT, pinned at `2fb2014` — see `vendor/PINS.lock`) as the FlipHouse P1 base.

FlipHouse adaptations on top of the fork:

- Peripheral upstream tooling dropped for P1 (Sentry, Storybook, semantic-release,
  checkly, crowdin, commitlint, lefthook, knip, bundle-analyzer).
- Toolchain reconciled with the monorepo harness: headless Node Vitest baseline
  (`apps/web/vitest.config.ts`), minimal Playwright landing smoke; lint/typecheck
  run via this package's own scripts.

## Auth (Clerk)

Linked to Clerk application `app_3F95DjSclyWOw7eHFfF8Af5XrNH`.

- `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY` lives in the committed `.env` (non-secret
  publishable key — swap to the FlipHouse app's `pk_…`).
- `CLERK_SECRET_KEY` is **never committed** — put it in `.env.local` (gitignored).
  Production keys are injected via Railway env (deploy steps 1.14–1.15).

## Commands

```bash
pnpm --filter web dev          # PGlite + migrate + next dev (localhost:3000)
pnpm --filter web build        # PGlite migrate + next build
pnpm --filter web test         # Vitest (headless Node baseline)
pnpm --filter web test:e2e     # Playwright landing smoke
pnpm --filter web check:types  # tsc --noEmit
```

Database: local **PGlite** (no Docker); production is a self-hosted Railway
Postgres plugin over the private network. No Supabase / cloud DB.
