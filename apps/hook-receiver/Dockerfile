# syntax=docker/dockerfile:1.7
# =============================================================================
# FlipHouse hook-receiver — tusd post-finish HTTP hook (Node-only HTTP service).
#
# Receives tusd `post-finish` POSTs on `/tus/post-finish`, claims the
# upload_ledger row (ON CONFLICT, idempotent) and enqueues the BullMQ flow via
# @fliphouse/worker-node's flow-producer. No Python / no ffmpeg — pure Node, so
# this image is small and fast (contrast the worker-node multi-runtime image).
#
# Build (from the REPO ROOT, not this dir — pnpm needs the whole workspace):
#   docker build -f apps/hook-receiver/Dockerfile -t fliphouse-hook-receiver .
# Syntax check only (BuildKit/Docker 24+):
#   docker build --check -f apps/hook-receiver/Dockerfile .
#
# Runtime env (injected by Railway variables — NEVER baked in):
#   DATABASE_URL  (Postgres, the upload_ledger authority)        — _PRIVATE_ URL
#   REDIS_URL     (BullMQ flow enqueue)                           — _PRIVATE_ URL
#   PORT          (Railway-injected; defaults to 8080)
#   HOST          (defaults to `::` dual-stack — leave unset on Railway)
# =============================================================================

ARG NODE_VERSION=24

# -----------------------------------------------------------------------------
# Stage 1 — node-builder: pnpm monorepo install + build the service subgraph.
# hook-receiver depends on @fliphouse/{shared,db,worker-node}; all must be
# present before install (workspace:* resolution) and built before this app.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS node-builder

# Corepack ships with Node; it pins the exact pnpm from package.json#packageManager.
RUN corepack enable

WORKDIR /repo

# Root workspace descriptors first — own cache layer.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY tsconfig.base.json tsconfig.json ./

# Internal workspace packages + apps this service builds against.
COPY packages ./packages
COPY apps/worker-node ./apps/worker-node
COPY apps/hook-receiver ./apps/hook-receiver

# Fetch the hook-receiver subgraph from the frozen lockfile, then build TS → dist.
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    pnpm install --frozen-lockfile --filter @fliphouse/hook-receiver...

RUN pnpm --filter @fliphouse/shared build \
    && pnpm --filter @fliphouse/db build \
    && pnpm --filter @fliphouse/worker-node build \
    && pnpm --filter @fliphouse/hook-receiver build

# Re-resolve to PRODUCTION-only node_modules (drops typescript/vitest); cheap,
# runs against the already-populated store. CI=true lets pnpm purge the dev
# modules dir non-interactively (no TTY in a docker build / Railway builder).
RUN --mount=type=cache,id=pnpm-store,target=/root/.local/share/pnpm/store \
    CI=true pnpm install --frozen-lockfile --prod --filter @fliphouse/hook-receiver...

# -----------------------------------------------------------------------------
# Stage 2 — runtime: the actual deployed image. Node only.
# Copy the WHOLE built workspace verbatim — pnpm node_modules are a symlink farm
# rooted at /repo/node_modules/.pnpm; a flattened COPY would dangle the symlinks.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runtime

RUN groupadd -r app && useradd -r -m -g app app

COPY --from=node-builder /repo /repo
WORKDIR /repo/apps/hook-receiver

USER app
ENV NODE_ENV=production

# HTTP service: tusd (private network) POSTs the post-finish hook here.
EXPOSE 8080

ENTRYPOINT ["node", "--enable-source-maps", "dist/server.js"]
