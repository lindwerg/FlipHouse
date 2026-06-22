# FlipHouse — production deploy runbook

The SINGLE multi-service runbook to take FlipHouse live on Railway + managed
Postgres/Redis/Cloudflare R2. Per-service deep wiring lives in
[`apps/worker-node/DEPLOY.md`](./apps/worker-node/DEPLOY.md) (cpu-worker +
hook-receiver internals); this document is the cross-service order, env, and
smoke-check contract. Every required env var is enumerated in
[`.env.example`](./.env.example) — this runbook tells you WHICH service gets
WHICH var and in WHAT order.

> Real provisioning is FOUNDER-GATED — it needs secrets and a GPU host. This
> file is the wiring contract; nothing here provisions infrastructure.

---

## 1. Service inventory

| Service | Railway build | Network | Replicas | Health |
| --- | --- | --- | --- | --- |
| **web** (Next.js) | RAILPACK — root [`railway.json`](./railway.json) | public | 2 | HTTP `GET /api/health` (probes DB + Redis) |
| **cpu-worker** (worker-node) | DOCKERFILE [`apps/worker-node/Dockerfile`](./apps/worker-node/Dockerfile) via [`apps/worker-node/railway.json`](./apps/worker-node/railway.json) | private (BullMQ consumer, **no HTTP port**) | **min 1** (never 0 — see DEPLOY.md) | process liveness + boot self-test, **no `healthcheckPath`** |
| **hook-receiver** | DOCKERFILE [`apps/hook-receiver/Dockerfile`](./apps/hook-receiver/Dockerfile) | public (tusd posts to it) | 1+ | HTTP server on `PORT`; boot fail-fast on missing env |
| **webhook-receiver** | DOCKERFILE [`apps/webhook-receiver/Dockerfile`](./apps/webhook-receiver/Dockerfile) | public (GPU posts to it) | 1+ | HTTP server on `PORT`; boot fail-fast on missing env |
| **gpu-gigaam** (founder-gated) | DOCKERFILE [`services/gpu-gigaam/Dockerfile`](./services/gpu-gigaam/Dockerfile) — **stub, does not build yet** | external GPU host (RunPod/Modal) | founder's choice | `GET /status/<id>` |
| Managed **Postgres** | Railway plugin | private | — | — |
| Managed **Redis** | Railway plugin | private | — | — |
| **R2** (Cloudflare) | external | public-read bucket for clips | — | — |
| **tusd** (founder-gated) | not repo-resident | public (browser uploads) | founder's choice | tusd built-in |

**Per-service Railway config path (mandatory):** Railway does NOT auto-discover a
subdirectory `railway.json`. For cpu-worker/hook-receiver/webhook-receiver set
the service's **Config-as-code path** to its `apps/<svc>/railway.json` (or set the
Dockerfile path directly). Without this a service rooted at the repo root
auto-detects the root `railway.json` and RAILPACK-builds **web** instead. See
DEPLOY.md for the cpu-worker failure mode in full.

---

## 2. Deploy order

Bring services up in dependency order — the producer side must be reachable
before the consumer scales:

1. **Managed Postgres** — healthy first (the ledger is the source of truth).
2. **Managed Redis** — BullMQ backend + park-key store.
3. **R2 bucket** — created, public-read, CORS set (founder-gated, §6).
4. **Migrations** — run via web's `preDeployCommand` (§3) before web serves.
5. **web** — Next app; `/api/health` green (DB + Redis reachable).
6. **cpu-worker** — scale only AFTER hook-receiver is healthy, so a job is never
   enqueued without a consumer. Keep `numReplicas >= 1`.
7. **hook-receiver** — owns the `FlowProducer`; tusd's `post-finish` lands here.
   Must be healthy before uploads complete or finished uploads have nowhere to
   enqueue. (Per DEPLOY.md this comes up just before cpu-worker scales.)
8. **webhook-receiver** — only needed for the GPU lane (`GPU_ASR_ENABLED=true`).
9. **gpu-gigaam + tusd** — FOUNDER-GATED (§6). The inline CPU path runs fully
   without the GPU lane; tusd is required for real browser uploads.

---

## 3. Database migrations (single drizzle chain)

There is ONE migration chain, owned by web. It runs as the web service's
**`preDeployCommand`** before the new web version serves traffic:

```
preDeployCommand: pnpm --filter web db:migrate   # = drizzle-kit migrate
```

(see root [`railway.json`](./railway.json) and `apps/web/package.json` →
`db:migrate`). All other services read the schema; none migrate.

**CI/deploy build dependency — build packages first.** The workspace packages
`@fliphouse/shared` and `@fliphouse/db` expose `dist/` via their package.json
`exports`. Apps resolve them through the node_modules symlink to `dist/`, NOT to
`src/`, and `dist/` is gitignored — a fresh checkout has none. So the
`build-packages` step in [`scripts/ci-local.sh`](./scripts/ci-local.sh)
(`pnpm -r --filter './packages/*' build`) MUST run before typecheck/coverage and
before any service build, or every cross-package import fails to resolve. The web
RAILPACK build runs `pnpm --filter @fliphouse/db build` first for the same reason.

---

## 4. GPU lane wiring (end to end)

The GPU ASR lane is armed by `GPU_ASR_ENABLED=true` on cpu-worker. When unset/
not-`"true"`, the inline CPU faster-whisper path runs and steps below are skipped.

**Shared-secret + URL wiring (all three must agree):**

| Var | Set on | Role |
| --- | --- | --- |
| `GPU_ASR_ENABLED=true` | cpu-worker | arms the submit-and-park lane |
| `GIGAAM_ENDPOINT` | cpu-worker | where the worker POSTs `/transcribe` |
| `GIGAAM_WEBHOOK_SECRET` | cpu-worker **+** gpu-gigaam (signer) **+** webhook-receiver (verifier) | HMAC key — **byte-identical on all three** |
| `WEBHOOK_PUBLIC_URL` | cpu-worker | public base; `/gpu/callback` is appended for the GPU to call back |

`resolveAsrEnv` (apps/worker-node/src/gpu/asr-env.ts) throws at boot if
`GPU_ASR_ENABLED=true` but any of `GIGAAM_ENDPOINT` / `GIGAAM_WEBHOOK_SECRET` /
`WEBHOOK_PUBLIC_URL` is missing — a misconfigured GPU lane fails the DEPLOY, not
every claimed ASR job one by one.

**End-to-end flow (upload → clip → publish → dashboard):**

1. Browser PATCHes video bytes to **tusd** (`NEXT_PUBLIC_TUS_ENDPOINT`, handed
   out by web's `/api/uploads/grant`).
2. On completion tusd fires `post-finish` → **hook-receiver** `/tus/post-finish`,
   which claims the `upload_ledger` row (idempotent `ON CONFLICT`) and enqueues
   the BullMQ Flow DAG.
3. **cpu-worker** drains the Flow stages (transcribe → score → cut → reframe →
   subtitle → polish). For long audio with the GPU lane on, the ASR stage
   **submits to gpu-gigaam and parks** (`park:<request_id>` in Redis).
4. **gpu-gigaam** transcribes and POSTs a **signed** result to
   `${WEBHOOK_PUBLIC_URL}/gpu/callback` → **webhook-receiver** verifies the HMAC
   (±300s replay window), atomically claims the park key (single `GETDEL`), writes
   the raw payload to R2, and enqueues `asr-resume` to continue the Flow.
5. On publish the worker promotes the finished clip to durable `clips/<hash>/` in
   R2 (content-hash key).
6. **web dashboard** lists clips and builds playback/download URLs as
   `${NEXT_PUBLIC_R2_PUBLIC_BASE}/${key}` (public-read bucket; presigned-URL route
   for private buckets is a founder-gated follow-up).

---

## 5. Per-service required env

Full placeholders + tags in [`.env.example`](./.env.example). Tags:
**SECRET** (never in repo/logs), **_PRIVATE_** (Railway private host),
**public** (`NEXT_PUBLIC_*`, in the browser bundle).

| Service | Required env | Tags |
| --- | --- | --- |
| **web** | `DATABASE_URL`, `REDIS_PRIVATE_URL`, `CLERK_SECRET_KEY`, `NEXT_PUBLIC_CLERK_PUBLISHABLE_KEY`, `NEXT_PUBLIC_TUS_ENDPOINT`, `NEXT_PUBLIC_R2_PUBLIC_BASE`, `PAYMENT_PROVIDER` (`tron` in prod), `TRON_HD_MNEMONIC` (tron) | DATABASE/REDIS `_PRIVATE_`; CLERK_SECRET_KEY + TRON_HD_MNEMONIC + TRONGRID_API_KEY **SECRET**; `NEXT_PUBLIC_*` public |
| **web** (optional) | `NEXT_PUBLIC_APP_URL`, `BILLING_PLAN_ENV`, `TRONGRID_API_KEY`, `TRON_RPC_URL`, `TRON_NETWORK`, `USDT_CONTRACT`, `TRON_CONFIRMATIONS`, Better Stack tokens | defaults in Env.ts |
| **cpu-worker** | `DATABASE_URL`, `REDIS_URL`, `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`; GPU lane: `GPU_ASR_ENABLED`, `GIGAAM_ENDPOINT`, `GIGAAM_WEBHOOK_SECRET`, `WEBHOOK_PUBLIC_URL` | DB/REDIS `_PRIVATE_`; R2 keys + `GIGAAM_WEBHOOK_SECRET` **SECRET** |
| **cpu-worker** (drain) | `RAILWAY_DEPLOYMENT_DRAINING_SECONDS`, `WORKER_SHUTDOWN_DEADLINE_MS` | tune per DEPLOY.md |
| **hook-receiver** | `DATABASE_URL`, `REDIS_URL` (+ optional `SWEEP_GRACE_TTL_MS`, `SWEEP_INTERVAL_MS`, `HOST`, `PORT`) | DB/REDIS `_PRIVATE_` |
| **webhook-receiver** | `GIGAAM_WEBHOOK_SECRET`, `REDIS_URL`, `R2_ACCOUNT_ID`, `R2_BUCKET`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY` | secret + R2 keys **SECRET**; REDIS `_PRIVATE_` |
| **gpu-gigaam** (founder-gated) | `GIGAAM_WEBHOOK_SECRET`, `HF_TOKEN` (+ `HOST`/`PORT`) | both **SECRET** |

### Key-rotation note

Treat these as rotatable secrets and **rotate immediately if any ever appears in
a chat, log, screenshot, or commit** (memory flags prior exposure risk):

- `OPENROUTER_API_KEY` (LLM scoring) — re-issue at OpenRouter, update the worker.
- `TRONGRID_API_KEY` — re-issue at TronGrid.
- `GIGAAM_WEBHOOK_SECRET` — rotate by setting the NEW value on cpu-worker,
  gpu-gigaam, and webhook-receiver; the receiver should accept old+new during the
  rotation window so in-flight callbacks are not rejected.
- `R2_ACCESS_KEY_ID` / `R2_SECRET_ACCESS_KEY` — roll the R2 token pair.
- `CLERK_SECRET_KEY`, `TRON_HD_MNEMONIC` — rotate at the source; the mnemonic
  rotation also re-derives every deposit address, so coordinate with the watcher.

Secrets live ONLY in Railway service variables / KMS, never in the repo, never
logged.

---

## 6. Smoke checks (per service, after deploy)

| Service | Smoke check |
| --- | --- |
| **web** | `curl -fsS https://<web>/api/health` → 200 with `db` + `redis` both `up`. A 503 means a dependency probe failed. |
| **cpu-worker** | Boot logs show the Python self-test passing (`fliphouse_worker.cli --selftest`) and no `resolveR2Env` / `resolveAsrEnv` throw. No HTTP port to curl — health is process liveness. |
| **hook-receiver** | Boot fail-fast: a missing `DATABASE_URL`/`REDIS_URL` exits with `missing required env var: <name>`. When healthy it listens on `PORT`; `POST /tus/post-finish` with a bad body returns `400` (not 5xx). |
| **webhook-receiver** | Boot fail-fast on missing `GIGAAM_WEBHOOK_SECRET`/`REDIS_URL`/R2. A `POST /gpu/callback` with a bad signature returns `401`. |
| **gpu-gigaam** | `GET /status/<id>` responds; a signed callback round-trips to the webhook-receiver. |
| **End-to-end** | Real upload → clip → publish → it appears on the creator dashboard with a working `${NEXT_PUBLIC_R2_PUBLIC_BASE}/${key}` playback URL. |
| **Billing guard** | With `NODE_ENV=production` + `PAYMENT_PROVIDER=mock`, the web app THROWS `MockProviderInProductionError` at provider construction (deploy fails loud). Setting `PAYMENT_PROVIDER=tron` clears it. |

---

## 7. FOUNDER-GATED checklist

These need secrets, a GPU host, or external infra and are NOT part of any CI
gate. Provision before the GPU/upload lanes go live:

- **GPU host** — RunPod **or** Modal (founder's choice). Needs CUDA + ffmpeg in
  the image; `services/gpu-gigaam/Dockerfile` is a **TODO stub that does not
  build yet**.
- **HF token** — `HF_TOKEN` with accepted terms for the gated pyannote VAD /
  segmentation models (used for 2h longform transcription).
- **GigaAM-v3 weights + model** — the `gigaam` package + `v3_e2e_rnnt`
  checkpoint on the GPU host. License risk accepted on SamurAIGPT/GigaAM.
- **CUDA Dockerfile build** — finish `services/gpu-gigaam/Dockerfile`; wire a
  real ASGI runner (uvicorn/hypercorn) and a durable status store
  (Redis/Postgres) so `GET /status` survives restarts/scale-out.
- **tusd deploy** — stand up tusd, point `post-finish` at the hook-receiver
  `/tus/post-finish`, and ensure **R2 multipart part-size parity**, **CORS** for
  the browser origin, and a **max upload size**. Wire `NEXT_PUBLIC_TUS_ENDPOINT`.
- **Secret provisioning + rotation** — provision all SECRET vars in Railway/KMS;
  follow the §5 key-rotation note. `GIGAAM_WEBHOOK_SECRET` must be byte-identical
  on cpu-worker, gpu-gigaam, and webhook-receiver.
- **Presigned-URL playback** — if the R2 bucket is made private, add the
  presigned-URL route behind the `toClipUrl` seam (MVP ships public-read).
