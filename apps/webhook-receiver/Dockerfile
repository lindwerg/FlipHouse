# syntax=docker/dockerfile:1.7
# =============================================================================
# FlipHouse webhook-receiver — GPU provider callback HTTP service (Node-only).
#
# Receives the GigaAM-v3 / GPU provider callback on `/gpu/callback`, verifies the
# HMAC (x-fliphouse-signature over `${timestamp}.${rawBody}`, ±300s replay
# window), atomically claims the parked job (single GETDEL on `park:<id>`), writes
# the raw payload to R2 and enqueues the `asr-resume` job. No Python / no ffmpeg.
#
# Build (from the REPO ROOT, not this dir — pnpm needs the whole workspace):
#   docker build -f apps/webhook-receiver/Dockerfile -t fliphouse-webhook-receiver .
# Syntax check only (BuildKit/Docker 24+):
#   docker build --check -f apps/webhook-receiver/Dockerfile .
#
# Runtime env (injected by Railway variables — NEVER baked in):
#   GIGAAM_WEBHOOK_SECRET  (HMAC shared secret with the GPU service)
#   REDIS_URL              (BullMQ asr-resume enqueue + park-key GETDEL) — _PRIVATE_
#   R2 creds               (@aws-sdk/client-s3: endpoint + key/secret + bucket)
#   PORT                   (Railway-injected; defaults to 8080)
#   HOST                   (defaults to `::` dual-stack — leave unset on Railway)
# =============================================================================

ARG NODE_VERSION=24

# -----------------------------------------------------------------------------
# Stage 1 — node-builder: pnpm monorepo install + build the service subgraph.
# webhook-receiver depends on @fliphouse/{shared,db}; both must be present before
# install (workspace:* resolution) and built before this app.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS node-builder

RUN corepack enable

WORKDIR /repo

COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY tsconfig.base.json tsconfig.json ./

COPY packages ./packages
COPY apps/webhook-receiver ./apps/webhook-receiver

RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter @fliphouse/webhook-receiver...

RUN pnpm --filter @fliphouse/shared build \
    && pnpm --filter @fliphouse/db build \
    && pnpm --filter @fliphouse/webhook-receiver build

# CI=true lets pnpm purge the dev modules dir non-interactively (no TTY in a
# docker build / Railway builder).
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    CI=true pnpm install --frozen-lockfile --prod --filter @fliphouse/webhook-receiver...

# -----------------------------------------------------------------------------
# Stage 2 — runtime: the actual deployed image. Node only.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runtime

RUN groupadd -r app && useradd -r -m -g app app

COPY --from=node-builder /repo /repo
WORKDIR /repo/apps/webhook-receiver

USER app
ENV NODE_ENV=production

# HTTP service: the GPU provider POSTs the signed callback here (public domain).
EXPOSE 8080

ENTRYPOINT ["node", "--enable-source-maps", "dist/server.js"]
