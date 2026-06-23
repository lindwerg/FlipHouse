# gpu-gigaam — GigaAM-v3 GPU transcription service (P2 step #1, TRACK D)

Self-hosted ASR service that the **worker-node** submits long audio to and that
POSTs the finished transcript back to the **webhook-receiver** as a signed
callback. This package is the **production-correct service skeleton**: the ASGI
app, the exact wire contracts, **real HMAC signing**, and the full
fetch → transcribe → sign-and-post orchestration — with the heavy ML and live I/O
behind injected seams.

> **What is real here vs. founder-gated** is the whole point of this README.
> Read the two tables below before wiring anything to a GPU.

---

## Wire contracts (match worker-node + webhook-receiver EXACTLY)

### 1. SUBMIT — `POST /transcribe` (worker-node → this service)

Request body:

```json
{
  "request_id": "<uuid>",
  "audio_url": "<https URL to fetch the audio>",
  "language": "ru",
  "webhook_url": "<url to POST the result to>",
  "output_prefix": "<str>"
}
```

Response: **synchronous `202`**, transcription runs in the background (never blocks
the response):

```json
{ "request_id": "<uuid>", "status": "accepted" }
```

Invalid body (missing/empty field, non-`https` URL, malformed JSON, oversize) →
`400 { "error": "<reason>" }`.

### 2. STATUS — `GET /status/<request_id>` (sweep → this service)

```json
{ "request_id": "<uuid>", "status": "processing" | "succeeded" | "failed", "error": "<str, only on failed>" }
```

Unknown id → `404`. **Skeleton uses an in-memory store** (`InMemoryStatusStore`);
production needs a durable store (see founder-gated table).

### 3. CALLBACK — `POST <webhook_url>` (this service → webhook-receiver)

Headers (computed for real, unit-tested against an independent recomputation):

```
x-fliphouse-signature: sha256=<hex(hmacSHA256(GIGAAM_WEBHOOK_SECRET, `${timestamp}.${rawBody}`))>
x-fliphouse-timestamp: <unix seconds>
content-type: application/json
```

The signed message is `${timestamp}.${rawBody}` over the **EXACT raw JSON bytes**
sent on the wire (serialized once, then both signed and POSTed — never re-encoded).

Success body:

```json
{
  "request_id": "<uuid>",
  "status": "succeeded",
  "engine": "gigaam-v3",
  "payload": {
    "duration": 0.0,
    "language": "ru",
    "segments": [
      { "start": 0.0, "end": 0.0, "words": [ { "word": "...", "start": 0.0, "end": 0.0 } ] }
    ]
  }
}
```

Failure body:

```json
{ "request_id": "<uuid>", "status": "failed", "error": "<str>" }
```

The `payload` shape is exactly what the receiver's `asr-finalize`
(`validate_gigaam_payload`) consumes: `{duration, language, segments:[{start,
end, words:[{word, start, end}]}]}`.

---

## What runs in CI (skeleton + fakes — 100% covered, no GPU/network)

| Module | What is REAL and unit-tested |
| --- | --- |
| `signing.py` | HMAC-SHA256 framing over `${timestamp}.${rawBody}`. A test recomputes the signature independently (exactly as the receiver verifies) and asserts a match, including a Cyrillic body. |
| `callback.py` | Body serialization (compact UTF-8, signed once), header assembly, `sign_and_post` orchestration, non-2xx + transport-error handling. Only the network POST is the injected `HttpPoster`. |
| `contracts.py` | Frozen `Word`/`Segment`/`RawPayload`/`SubmitRequest` + `to_dict` projections matching the receiver. |
| `transcribe.py` | The PURE GigaAM-longform → contract mapping (`text`→`word` rename, window-offset add, duration compute) and model-fault wrapping, driven by a `FakeModel`. |
| `validate.py` | Required-field + `https`-scheme validation of the submit body. |
| `status_store.py` | In-memory status transitions (processing/succeeded/failed) the sweep reads. |
| `orchestrator.py` | The full job: fetch → transcribe → sign-and-post(succeeded); on any exception → mark-failed + sign-and-post(failed); failure-callback-undeliverable still leaves a terminal status. All seams faked. |
| `app.py` | ASGI `/transcribe` (202 + schedule) and `/status/<id>`, driven directly via fake `receive`/`send` — no live socket. |

Run it:

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
ruff check . && black --check . && python -m pytest    # 100% coverage gate
```

---

## FOUNDER-GATED (live path — `# pragma: no cover`, not exercised in CI)

These seams have REAL default implementations whose bodies are pragma'd because
they need a GPU, model weights, gated HuggingFace models, or live network. Tests
inject fakes; the real bodies are wired but only exercised on the GPU host.

| Concern | Where | What the founder must provision |
| --- | --- | --- |
| **GigaAM-v3 weights + model** | `transcribe.py::_build_real_model` | `gigaam` package + the `v3_e2e_rnnt` checkpoint. License risk accepted on SamurAIGPT/GigaAM (see memory). |
| **pyannote VAD (2h longform)** | `transcribe.py` (via `transcribe_longform`) | `pyannote.audio` + a **HuggingFace token** with accepted terms for the gated VAD/segmentation models. |
| **GPU host** | deploy | RunPod **or** Modal — choice is founder's. Needs CUDA + ffmpeg in the image (see Dockerfile stub). |
| **Audio fetch** | `audio.py::_default_fetch_audio` | `httpx` streaming download of `audio_url`. Prod should add SSRF allow-listing of source hosts. |
| **Callback transport** | `config.py::_httpx_poster` | `httpx.Client` POST to `webhook_url`. |
| **Background scheduler** | `app.py::_default_schedule` | Runs the job off the event loop. Prod should use a real queue/worker (single-replica `run_in_executor` is the skeleton default), so a crash mid-job is recoverable. |
| **`GIGAAM_WEBHOOK_SECRET`** | env | The HMAC key **shared with the webhook-receiver**. Provision in the GPU host's secret store; **rotate** by setting the new value on BOTH sides (receiver accepts old+new during the rotation window). Never commit. |
| **Durable status store** | `status_store.py` | The in-memory store is per-process and lost on restart / not shared across replicas. Prod needs Redis/Postgres so the sweep's `GET /status` survives restarts and scale-out. |

### Required env vars

| Var | Required | Purpose |
| --- | --- | --- |
| `GIGAAM_WEBHOOK_SECRET` | **yes** | HMAC key for callback signing; must equal the receiver's. |
| `HOST` / `PORT` | no | ASGI bind address (founder's web server / ASGI runner owns this). |
| `HF_TOKEN` | live only | HuggingFace token for the gated pyannote VAD models. |

---

## Live proof (founder-run)

The `# pragma: no cover` real-model path (`_build_real_model`,
`payload_from_longform` against a live `LongformTranscriptionResult`) is verified
by an **end-to-end live run**, not by CI. See
[`docs/ci/live-eval-runbook.md`](../../docs/ci/live-eval-runbook.md) for the exact
one-command steps: HF token (gated pyannote), `modal deploy`, flipping
`GPU_ASR_ENABLED` + `GIGAAM_ENDPOINT` on the worker, and running
`python scripts/live_eval.py gigaam` to prove the lane.

---

## Status / not in scope for this skeleton

- No live ASGI server runner (uvicorn/hypercorn) is wired — `create_app` /
  `build_app_from_env` return the app; the founder picks the runner.
- No retry/backoff on the callback POST — the orchestrator marks `failed` and
  relies on the sweep's `GET /status` as the backstop. Add retry when the queue is
  introduced.
- The `Dockerfile` is a **TODO stub** — it does not build.
