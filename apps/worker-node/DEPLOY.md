# FlipHouse CPU worker — deploy runbook

Ops reference for the `cpu-worker` service (this app) and its sibling
`hook-receiver`. The image is built from [`Dockerfile`](./Dockerfile): one
container where the Node BullMQ worker is PID 1 and spawns
`python -m fliphouse_worker.cli <stage>` per stage.

> Real deploy is NOT part of this checkpoint — it needs secrets. This document
> is the wiring contract; nothing here provisions infrastructure.

## Required environment variables

Injected via Railway service variables — **never** baked into the image.

| Variable | Purpose | Notes |
| --- | --- | --- |
| `DATABASE_URL` | Postgres ledger (`claimUpload`/`recordFailure`/`upsertClips`/…) | Use the `_PRIVATE_` host on Railway (private network, no egress fee). |
| `REDIS_URL` | BullMQ Flow queues + QueueEvents | Use the `_PRIVATE_` host. |
| `R2_ACCOUNT_ID` | Cloudflare R2 account | — |
| `R2_BUCKET` | R2 bucket holding source + clip artifacts | — |
| `R2_ACCESS_KEY_ID` | R2 S3 credential | Secret. |
| `R2_SECRET_ACCESS_KEY` | R2 S3 credential | Secret. |

`resolveR2Env` (src/r2/build-r2-client.ts) throws on the first missing `R2_*`,
and `runWorkers` throws on a missing `DATABASE_URL`/`REDIS_URL` — so a
misconfigured deploy fails fast at boot rather than mid-job.

### Drain / shutdown knobs (graceful redeploy)

| Variable | Purpose | Notes |
| --- | --- | --- |
| `RAILWAY_DEPLOYMENT_DRAINING_SECONDS` | Grace Railway gives between SIGTERM and SIGKILL on a redeploy. | **Set this** — it defaults to ~0s, which defeats the graceful drain entirely (SIGKILL mid-render). Set it ABOVE the longest stage you expect to drain, but know Railway caps it; a stage longer than the cap is cut and re-claimed (idempotent → redundant render, never corruption). |
| `WORKER_SHUTDOWN_DEADLINE_MS` | Backstop: force-exit if a graceful drain hasn't finished in time. | Default 30000. Set it just UNDER `RAILWAY_DEPLOYMENT_DRAINING_SECONDS × 1000` so a hung `worker.close()` exits cleanly (non-zero) instead of being SIGKILLed mid-write. A second SIGTERM during drain also force-exits immediately. |

The per-stage `STAGE_TIMEOUT_MS` (queue-config.ts) is what bounds any single
in-flight stage: a wedged ffmpeg/MediaPipe is aborted (process-group kill) at its
timeout — strictly below `LOCK_DURATION_MS`, so it is killed and retried before
BullMQ's stall recovery can double-run it. Keep these timeouts within the drain
window so a redeploy can finish in-flight work rather than abandon it.

Baked into the image (do not override unless you know why):

- `FLIPHOUSE_PYTHON=/usr/bin/python3` — the interpreter that has the wheel +
  `[transcription,reframe]` extras installed. Stages spawn this.
- `NODE_ENV=production`.

## Start order of Railway services

Bring services up in dependency order; the producer side must be reachable
before the consumer scales:

1. **Postgres** — healthy first (ledger is the source of truth).
2. **Redis** — BullMQ backend.
3. **hook-receiver** — owns the `FlowProducer`. tusd's `post-finish` hook lands
   here and enqueues the Flow DAG. If it is not healthy before uploads complete,
   finished uploads have nowhere to enqueue. It exposes the HTTP healthcheck.
4. **cpu-worker** (this service) — scale only AFTER hook-receiver is healthy, so
   a job is never enqueued without a consumer eventually draining it.

### Worker replica invariant: `min: 1`

The worker must keep at least one always-on replica. BullMQ jobs sit in Redis
until a worker pulls them; scaling to zero strands every enqueued Flow until the
next scale-up. Keep `numReplicas >= 1` (a.k.a. `min: 1`).

### No `healthcheckPath` for cpu-worker

This service is a **BullMQ consumer, not an HTTP server** — `run-workers.ts`
opens no port. Do not set `healthcheckPath` for it; Railway derives health from
process liveness + restart policy. The HTTP healthcheck belongs to the
hook-receiver. A boot-time `runPythonSelftest()` runs
`python -m fliphouse_worker.cli --selftest` before any job is pulled, so a broken
Python image (missing wheel, MediaPipe `ImportError`) fails the deploy outright
instead of failing every stage one by one.

### `railway.json` (worker service)

This service's config lives at [`apps/worker-node/railway.json`](./railway.json)
(builder `DOCKERFILE`, `numReplicas: 1`, `restartPolicyType: ON_FAILURE`, no
`healthcheckPath`). It is SEPARATE from the repo-root `railway.json`, which is the
RAILPACK **web** service.

**Mandatory wiring (the file alone is not enough):** Railway does NOT auto-discover
a per-service config from a subdirectory. In the cpu-worker service settings, set
the **Config-as-code path** to `/apps/worker-node/railway.json`. Without it, a
worker service rooted at the repo root auto-detects the root `railway.json`,
RAILPACK-builds **web** instead of this Dockerfile, and may bolt `/api/health`
onto an HTTP-less BullMQ consumer → boot/liveness failure.

Notes: no `healthcheckPath`, and `numReplicas` floors the `min: 1` invariant.
`startCommand` mirrors the image `ENTRYPOINT` (and is redundant with it). The
build context is the repo root (pnpm needs the whole workspace), so the Dockerfile
path is repo-root-relative as shown.

## Graceful shutdown (drain, never abandon)

On `SIGTERM`/`SIGINT`, `runWorkers().shutdown()` drains in order:

1. `worker.close()` per queue — stops fetching, lets the **in-flight** stage
   finish (ffmpeg/MediaPipe/upload completes and writes its sentinel).
2. `projector.close()` — stops the QueueEvents read-side.
3. `pool.end()` — closes the Postgres pool last.

This is why a redeploy does not double-run or corrupt an in-flight render: the
running stage completes before the process exits.

## Two-phase removal of the store handler

The Python `store_handler` (R2 upload of the finished clip) must not be killed
**mid-upload** — a half-written object plus a missing finish-sentinel forces a
redundant re-render on retry. When you need to remove or replace the store
behavior, do it in two phases, never a hard kill:

1. **Drain** — scale `min: 1 → 1` and send `SIGTERM`; let `worker.close()` finish
   any in-flight upload (graceful shutdown above guarantees the sentinel is
   written). Do not remove the service yet.
2. **Remove** — only once no job is in flight (queues drained, no active stage),
   remove/replace the handler. Then redeploy.

Skipping phase 1 risks a partially uploaded clip with no finish marker.

## Image size expectation

The `[transcription,reframe]` extras pull `ctranslate2` (~200 MB) plus
`opencv-python-headless`, so the final image lands around **3–4 GB**. This is
expected; Railway bills image storage accordingly. The from-source FFmpeg stage
can be swapped for a pinned prebuilt LGPL image (see the Dockerfile comment on
`ffmpeg-builder`) to cut build minutes if cost matters.

## Input codec support (decode)

The proxy transcode + finalist cutter must DECODE whatever users upload or yt-dlp
pulls. The built FFmpeg decodes:

- **AV1** — via the BSD-2 `dav1d` lib (`--enable-libdav1d`, runtime `libdav1d6`).
  This is the YouTube 1080p+ default and the ONE codec with no fast native FFmpeg
  decoder. Without dav1d, AV1 sources fail the proxy transcode (ffmpeg exits
  non-zero / 69, "Decoder not found"). This is decode-only — dav1d has no encoder.
- **HEVC (H.265)** and **VP9** — native FFmpeg decoders, already in the binary
  with no extra lib (default iPhone/desktop record + common WebM/YouTube fallback).

A build-time guard in the Dockerfile (`ffmpeg -decoders | grep -q ...` for
`libdav1d`/`hevc`/`vp9`) FAILS the image build if any of these decode paths
regress — mirroring the fc-list Montserrat and YuNet sha256 self-tests. Encoders
are unchanged: delivered clips stay `libopenh264` (LGPL), the internal proxy stays
`libx264` (GPL), the finalist cutter stays `libvpx-vp9` + `libopus`.

**Smoke test after deploy** (the `-decoders` grep is necessary but not sufficient):
run a real AV1 file — e.g. a `yt-dlp` of a YouTube 1080p — through the actual
ingest→transcode lane and confirm exit 69 is gone end-to-end.
