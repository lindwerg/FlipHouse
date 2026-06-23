# gpu-asd — LR-ASD GPU active-speaker service (REFRAME Phase 4)

Self-hosted **active-speaker detection** the **worker-node** calls inline during the
vertical reframe. It fixes the profile / who-to-follow case: follow whoever is
**SPEAKING** (usually frontal), not a larger silent/turned head. The worker already
detects faces on CPU (YuNet/MediaPipe); this service runs **LR-ASD** over those face
tracks and returns a per-frame per-face speaking score, which overrides the CPU
frontal-largest heuristic.

> **Model:** [Junhua-Liao/LR-ASD](https://github.com/Junhua-Liao/LR-ASD) — **MIT**,
> **pinned** at commit `1b6dcd2d8fc2895683de6508ec6294ec47d388ca`, bundled weights
> (`weight/finetuning_TalkSet.model`, fallback `weight/pretrain_AVA.model`), S3FD face
> detector (bundled). **NO pyannote, NO gated checkpoints, NO Ultralytics/InsightFace**
> — clean for commercial use.

This package is the **production-correct service code**: the ASGI app, the exact wire
contract, **real HMAC verification**, and the validate → verify → score → respond
orchestration — with the heavy LR-ASD model behind ONE injected seam. The package is
**100% unit-covered** (stdlib only). The GPU model, the image, and the Modal deploy
live in `modal_app.py` + `lr_asd_runner.py` + `lr_asd_eval.py` (**deploy-only**,
outside the coverage gate — same split as `gpu-gigaam`).

---

## Wire contract (matches the worker's ASD seam EXACTLY)

### `POST /score` (worker → this service) — **synchronous**

Unlike GigaAM's submit-and-park lane, `/score` returns the result in the **same
response** (the worker blocks on it during the render).

Request headers (HMAC, identical framing to the GigaAM webhook):

```
x-fliphouse-timestamp: <unix-seconds>
x-fliphouse-signature: sha256=<hex(hmacSHA256(GPU_ASD_SECRET, `${ts}.${rawBody}`))>
```

Request body:

```json
{
  "proxy_url": "<https URL to the proxy/source>",
  "start": 12.0,
  "end": 41.0,
  "sample_fps": 2.0,
  "frames": [
    [{ "x": 100, "y": 80, "w": 120, "h": 120 }, { "x": 700, "y": 90, "w": 110, "h": 110 }],
    [{ "x": 102, "y": 82, "w": 120, "h": 120 }]
  ]
}
```

`frames[i][j]` is the worker's CPU-detected face `j` in sampled frame `i`. The
response score grid mirrors this ragged shape EXACTLY.

Response `200`:

```json
{ "engine": "lr-asd", "scores": [[0.95, 0.02], [0.88]] }
```

| Status | When |
|--------|------|
| `200`  | scored; `scores[i][j]` = speaking confidence `[0,1]` for `frames[i][j]` |
| `400`  | malformed JSON / bad body shape / oversize / non-`https` `proxy_url` |
| `401`  | missing or invalid HMAC signature |
| `500`  | model fault or mis-shaped grid (worker **fails open to its CPU heuristic**) |

### `GET /health` → `200 { "status": "ok" }`

---

## What is real here vs. deploy-only

| Real + 100% unit-covered (`fliphouse_asd/`) | Deploy-only (service root, GPU image) |
|---|---|
| `app.py` — signed `/score` ASGI, 4xx/5xx mapping | `modal_app.py` — Modal GPU app + image |
| `signing.py` — HMAC verify (mirrors worker signer) | `lr_asd_runner.py` — S3FD track + score projection |
| `validate.py` — body → `ScoreRequest` | `lr_asd_eval.py` — upstream `evaluate_network` adapter |
| `contracts.py` / `scoring.py` — shape-check + clamp | the cloned LR-ASD repo + weights (baked in image) |

The package's pytest gate is `--cov-fail-under=100`; the deploy-only files import
torch/cv2 + the LR-ASD repo (present only in the Modal image) and are never collected.

---

## Deploy

```bash
# from services/gpu-asd
modal secret create fliphouse-asd GPU_ASD_SECRET=<same-secret-as-the-worker>
modal deploy modal_app.py          # builds the GPU image (clones LR-ASD + weights)
modal run    modal_app.py --selftest   # signs a request → asserts 200 + shaped grid
```

`--selftest` exercises the whole request path (HMAC + validate + app) with a FAKE
in-process scorer, so it needs no GPU and proves the contract is intact in the
deployed image before the worker is pointed at it.

> **Real inference is wired.** `lr_asd_eval.evaluate_track` now mirrors the pinned
> `Columbia_test.evaluate_network` preprocessing + forward exactly (median-smoothed
> `cropScale` crop → 224-resize → 112 center-crop; 16 kHz MFCC at the 100:25 audio:video
> ratio; `_DURATION_SET` averaging; `forward_audio_frontend` / `forward_visual_frontend`
> / `forward_audio_visual_backend` → `lossAV.forward(out, labels=None)`), producing one
> speaking score per face per frame. **Validate on first GPU deploy** with a real signed
> `/score` against a known clip (see below); the worker still **fails open to its CPU
> YuNet/MediaPipe selector** on any non-2xx, so a model fault never breaks a render.

### Validate real scores after deploy

```bash
# After `modal deploy`, sign a real /score (a window with two faces, one speaking) and
# confirm the speaking face scores HIGHER than the silent one:
curl -sS -X POST "https://<modal-app>.modal.run/score" \
  -H "x-fliphouse-timestamp: $(date +%s)" \
  -H "x-fliphouse-signature: sha256=<hmac>" \
  -d '{"proxy_url":"https://<known-clip>.mp4","start":0,"end":4,"sample_fps":2,
       "frames":[[{"x":..,"y":..,"w":..,"h":..},{"x":..,"y":..,"w":..,"h":..}]]}'
# → 200 {"engine":"lr-asd","scores":[[0.9,0.1]]}  (speaking face > silent face)
```

---

## Wire the worker (cpu-worker env)

```
GPU_ASD_ENABLED=true
GPU_ASD_ENDPOINT=https://<modal-app>.modal.run
GPU_ASD_SECRET=<same-secret-as-the-modal-secret>
```

With the flag off (default) the worker uses the CPU heuristic and never calls this
service. See `fliphouse_worker.clipping.build_speaker_region_selector`.
