# syntax=docker/dockerfile:1.7
# =============================================================================
# FlipHouse CPU worker — single image, Node PID 1 + Python sidecar.
#
# The Node BullMQ worker (`node dist/worker/run-workers.js`) is PID 1; for every
# stage it spawns `python -m fliphouse_worker.cli <stage>` as a subprocess (see
# apps/worker-node/src/python/spawn.ts + resolve-entry.ts). Both runtimes MUST
# live in the same image, plus a CPU-only LGPL FFmpeg (libopenh264) on PATH.
#
# Sizing (roadmap §Railway): CPU-only, ~1.5–2.5 GB RAM/task. ASR runs on the GPU
# submit-and-park lane (GigaAM-v3), so no whisper runtime ships here; the MediaPipe
# reframe extra pushes the final image to ~2–3 GB (opencv).
#
# Build (from the REPO ROOT, not this dir — pnpm needs the whole workspace):
#   docker build -f apps/worker-node/Dockerfile -t fliphouse-worker .
# Syntax check only (no build, BuildKit/Docker 24+):
#   docker build --check -f apps/worker-node/Dockerfile .
# Or lint without Docker:
#   docker run --rm -i hadolint/hadolint < apps/worker-node/Dockerfile
#
# Secrets (R2_*, DATABASE_URL, REDIS_URL) are NEVER baked in — injected by
# Railway variables at runtime. See apps/worker-node/DEPLOY.md.
# =============================================================================

ARG NODE_VERSION=24
ARG PYTHON_VERSION=3.11
ARG FFMPEG_VERSION=7.1

# -----------------------------------------------------------------------------
# Stage 1 — ffmpeg-builder: compile FFmpeg 7.1 (GPL) with libopenh264 + libx264.
#
# We build from source so the binary is CPU-only. It is GPL (--enable-gpl
# --enable-libx264): GPL libx264 is founder-approved for commercial use and is
# used ONLY by the INTERNAL 720p proxy transcode (stages/_types.py), which is
# never delivered. DELIVERED clips (clipping/render.py + the caption burn) STILL
# encode with LGPL libopenh264 — both encoders ship in this one binary, and
# render_preflight still asserts libopenh264 is present. openh264 is fetched as
# Cisco's prebuilt LGPL .so + headers — its source is published separately from
# FFmpeg under Cisco's binary-license model.
#
# COST NOTE (roadmap risk): a from-source build is ~15–40 min and ~4 GB RAM on
# the Railway builder (8 GB cap). If build minutes/cost matter, replace this
# whole stage with a pinned prebuilt LGPL image, e.g.:
#   FROM mwader/static-ffmpeg:7.1 AS ffmpeg-builder
# and drop the COPY of /usr/local/bin/ffmpeg below to /ffmpeg /ffprobe.
# -----------------------------------------------------------------------------
FROM debian:bookworm-slim AS ffmpeg-builder

ARG FFMPEG_VERSION
# SHA-256 of ffmpeg-${FFMPEG_VERSION}.tar.xz, verified below. MUST be bumped in
# lockstep with FFMPEG_VERSION — a version bump without a matching digest fails
# the build loudly (the point). Value for 7.1, computed from ffmpeg.org.
ARG FFMPEG_SHA256=40973d44970dbc83ef302b0609f2e74982be2d85916dd2ee7472d30678a7abe6

# libass (+ freetype/fontconfig/fribidi/harfbuzz) is required to compile FFmpeg
# with --enable-libass, the subtitle renderer the caption burn-in (-vf subtitles=)
# uses. libx264-dev provides the GPL H.264 encoder used by the internal proxy
# transcode only (--enable-gpl below).
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
      build-essential \
      ca-certificates \
      nasm \
      pkg-config \
      wget \
      libopenh264-dev \
      libopenh264-7 \
      libx264-dev \
      libass-dev \
      libfreetype6-dev \
      libfontconfig1-dev \
      libfribidi-dev \
      libharfbuzz-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build

# Pinned source tarball, integrity-checked against FFMPEG_SHA256 before unpacking
# so a poisoned mirror / cache / DNS-hijack of the (HTTPS) download is rejected —
# this binary decodes attacker-controlled user video in production.
RUN wget -q "https://ffmpeg.org/releases/ffmpeg-${FFMPEG_VERSION}.tar.xz" -O ffmpeg.tar.xz \
    && echo "${FFMPEG_SHA256}  ffmpeg.tar.xz" | sha256sum -c - \
    && tar -xf ffmpeg.tar.xz \
    && mv "ffmpeg-${FFMPEG_VERSION}" ffmpeg-src

WORKDIR /build/ffmpeg-src

# GPL build: --enable-gpl --enable-libx264 (proxy transcode only); NO
# --enable-nonfree. libopenh264 stays for DELIVERED clips; --enable-libass turns
# on the -vf subtitles= filter (caption burn-in).
RUN ./configure \
      --prefix=/usr/local \
      --enable-shared \
      --disable-static \
      --disable-doc \
      --disable-debug \
      --enable-gpl \
      --enable-libx264 \
      --enable-libopenh264 \
      --enable-libass \
      --enable-pic \
    && make -j"$(nproc)" \
    && make install

# -----------------------------------------------------------------------------
# Stage 2 — node-builder: pnpm monorepo install + worker-node build.
#
# COPY ORDER MATTERS: workspace root manifests + lockfile first (cacheable
# install layer), then the workspace packages, then this app. pnpm resolves the
# `workspace:*` deps (@fliphouse/shared, @fliphouse/db) from packages/, so they
# MUST be present before install. NODE_ENV is left unset until after the build
# so devDependencies (typescript, vitest) are installed for `pnpm ... build`.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS node-builder

# Corepack ships with Node; it pins the exact pnpm from package.json#packageManager.
RUN corepack enable

WORKDIR /repo

# Root workspace descriptors (lockfile + workspace map) — own cache layer.
COPY pnpm-lock.yaml pnpm-workspace.yaml package.json ./
COPY tsconfig.base.json tsconfig.json ./

# Internal workspace packages the worker depends on (build deps).
COPY packages ./packages
COPY apps/worker-node ./apps/worker-node

# Fetch the worker subgraph from the frozen lockfile, then build TS → dist.
RUN \
    pnpm install --frozen-lockfile --filter @fliphouse/worker-node...

RUN pnpm --filter @fliphouse/shared build \
    && pnpm --filter @fliphouse/db build \
    && pnpm --filter @fliphouse/worker-node build

# Re-resolve to PRODUCTION-only node_modules for the runtime image (drops
# typescript/vitest). Runs against the already-populated store, so it is cheap.
# CI=true lets pnpm purge the dev modules dir non-interactively (no TTY in a
# docker build / Railway builder) — without it pnpm aborts the --prod re-resolve.
RUN \
    CI=true pnpm install --frozen-lockfile --prod --filter @fliphouse/worker-node...

# -----------------------------------------------------------------------------
# Stage 3 — runtime: Node + Python 3.11 + ffmpeg, the actual deployed image.
#
# libgl1 + libglib2.0-0 are MANDATORY: MediaPipe (via opencv-python-headless)
# dlopen's libGL.so.1 / libgthread-2.0 at import time. Without them the reframe
# stage import explodes into a fatal IMPORT_ERROR with no retry. The python3
# package gives us 3.11 on bookworm.
# -----------------------------------------------------------------------------
FROM node:${NODE_VERSION}-bookworm-slim AS runtime

# fontconfig + libass9 (and its runtime deps: freetype, fribidi, harfbuzz) are
# MANDATORY for the caption burn-in: the FFmpeg subtitles= filter dlopen's libass,
# which resolves the Montserrat face through fontconfig. Without fontconfig +
# fc-cache the ASS Fontname would not resolve and captions would render in a
# fallback font (or nothing).
# hadolint ignore=DL3008
RUN apt-get update && apt-get install -y --no-install-recommends \
      python3 \
      python3-pip \
      python3-venv \
      ca-certificates \
      libopenh264-7 \
      libx264-164 \
      libgl1 \
      libglib2.0-0 \
      libgles2 \
      libegl1 \
      libgomp1 \
      fontconfig \
      libass9 \
      libfreetype6 \
      libfribidi0 \
      libharfbuzz0b \
    && rm -rf /var/lib/apt/lists/*

# FFmpeg LGPL binaries + shared libs from the builder.
COPY --from=ffmpeg-builder /usr/local/bin/ffmpeg /usr/local/bin/ffmpeg
COPY --from=ffmpeg-builder /usr/local/bin/ffprobe /usr/local/bin/ffprobe
COPY --from=ffmpeg-builder /usr/local/lib/ /usr/local/lib/
RUN ldconfig && ffmpeg -version

# Caption font: install the vendored SIL-OFL Montserrat ExtraBold into the system
# font path, rebuild the fontconfig cache, and HARD-VERIFY the family is visible.
# The `fc-list | grep` is a BUILD-FAILING guard: the ASS Fontname ("Montserrat
# ExtraBold") MUST match the family fontconfig reports, or libass silently falls
# back. A missing/misnamed font fails the image build here, not silently in prod.
COPY services/ai-worker-python/fliphouse_worker/captioning/fonts/Montserrat-ExtraBold.ttf \
     /usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf
RUN chmod 644 /usr/share/fonts/truetype/montserrat/Montserrat-ExtraBold.ttf \
    && fc-cache -f \
    && fc-list | grep -i montserrat

# Python sidecar: install the service wheel + CPU transcription/reframe extras.
# --break-system-packages: this is a single-purpose container, no system pip to
# protect. The libgl1 apt layer above (not pip pinning) is what keeps MediaPipe
# importable.
WORKDIR /srv/ai-worker-python
# Copy ONLY the wheel inputs — pyproject (static version, explicit packages) plus
# the package (its package-data ships the vendored BlazeFace .tflite). This omits
# tests/, the host .venv (~700 MB), and the mypy/ruff/pytest caches that a bare
# `COPY . ./` would otherwise bake into the image.
COPY services/ai-worker-python/pyproject.toml ./
COPY services/ai-worker-python/fliphouse_worker ./fliphouse_worker
RUN pip3 install --no-cache-dir --break-system-packages '.[transcription,reframe]' \
    && python3 -m fliphouse_worker.cli --selftest

# Node worker: copy the WHOLE built workspace verbatim. pnpm node_modules are a
# symlink farm rooted at /repo/node_modules/.pnpm; the worker's own
# node_modules symlink into it by relative path, so the /repo layout must be
# preserved exactly (a flattened COPY would dangle every symlink).
COPY --from=node-builder /repo /repo
WORKDIR /repo/apps/worker-node

# Drop root for the actual workload: this container's whole job is decoding
# attacker-controlled media through native ffmpeg/MediaPipe, so it must not run
# as root. No `chown -R` needed — COPY leaves /repo + site-packages
# world-readable, and stages write only to per-job tempfile dirs ($TMPDIR) and
# the user's HOME (-m) for any opencv/mediapipe caches. PGID-kill in spawn.ts
# stays same-uid. pip-install + selftest above intentionally ran as build-time
# root.
RUN groupadd -r app && useradd -r -m -g app app
USER app

# resolve-entry.ts reads FLIPHOUSE_PYTHON; pin it to the interpreter that has the
# wheel installed so spawned stages never fall back to a bare `python`.
ENV FLIPHOUSE_PYTHON=/usr/bin/python3
ENV NODE_ENV=production

# No EXPOSE / healthcheck port: this is a BullMQ consumer, not an HTTP server.
# Railway health is derived from process liveness; the HTTP healthcheck lives on
# the sibling hook-receiver service (see DEPLOY.md). Binds (Redis/PG) reach the
# Railway private network over the _PRIVATE_ URLs.
ENTRYPOINT ["node", "dist/worker/run-workers.js"]
