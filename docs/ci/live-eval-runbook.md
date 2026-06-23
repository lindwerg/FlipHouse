# Live eval runbook — proving the P2 quality bar (#4)

CI proves the eval **machinery** (Spearman / dispersion / sub-score divergence /
cutover) on deterministic mocks. It can NOT prove the two product claims that need
real, paid inference:

1. **"best RU ASR"** — GigaAM-v3 actually transcribes the canonical Russian source.
2. **"the cascade beats text-only"** — native A/V scoring ranks clips at least as
   well as the text-only path (the cutover gate).

This runbook is the single source of truth for running both, by hand, with live
secrets. Nothing here runs in CI; every command is opt-in and fails fast without
its keys.

---

## 0. Prerequisites (one-time)

### 0.1 HuggingFace token for the gated pyannote VAD

GigaAM-v3 longform (the 2-hour case) uses **pyannote** VAD windowing, whose
`pyannote/segmentation-3.0` checkpoint is a **gated** HF model — the download 401s
until you accept its terms with your account.

1. Sign in at <https://huggingface.co>.
2. Open <https://huggingface.co/pyannote/segmentation-3.0> and click **Agree and
   access repository** (accept the user conditions). Do the same for
   <https://huggingface.co/pyannote/voice-activity-detection> if prompted.
3. Create a token at <https://huggingface.co/settings/tokens> → **New token** →
   type **Read**. Copy it — this is your `HF_TOKEN`.

> Without the accepted terms the token exists but the VAD download still 401s.
> Acceptance is per-account, not per-token.

### 0.2 OpenRouter key for Gemini scoring

`OPENROUTER_API_KEY` — your paid OpenRouter key (the scoring routes pin Gemini via
Vertex for inline base64 video). Top up enough for a few dozen clip scores.

---

## 1. Deploy GigaAM-v3 to Modal and flip the worker over

### 1.1 Provision the Modal secret

The deploy reads one Modal secret named `fliphouse-gigaam` with two keys:

```bash
modal secret create fliphouse-gigaam \
  GIGAAM_WEBHOOK_SECRET="<same value as the webhook-receiver's secret>" \
  HF_TOKEN="<your read token from 0.1>"
```

`GIGAAM_WEBHOOK_SECRET` **must equal** the webhook-receiver's secret — the receiver
verifies the HMAC the GPU signs. If you rotate it, set the new value on BOTH sides.

### 1.2 Deploy

```bash
cd services/gpu-gigaam
modal deploy modal_app.py
```

Modal prints the `web` function URL, e.g.
`https://<workspace>--fliphouse-gigaam-web.modal.run`. That base URL is your
`GIGAAM_ENDPOINT`. Confirm it is up:

```bash
curl -s "$GIGAAM_ENDPOINT/health"      # → {"status":"ok"}
```

### 1.3 Flip the worker-node onto the GPU lane

On the **cpu-worker** Railway service set (see `apps/worker-node/src/gpu/asr-env.ts`
— all four are required together, a missing one fails the deploy on purpose):

```
GPU_ASR_ENABLED   = true
GIGAAM_ENDPOINT   = https://<workspace>--fliphouse-gigaam-web.modal.run
GIGAAM_WEBHOOK_SECRET = <same secret as the Modal secret + the receiver>
WEBHOOK_PUBLIC_URL    = https://<webhook-receiver>/gigaam/callback
```

Redeploy the worker. ASR jobs now park on GigaAM-v3 instead of the faster-whisper
CPU fallback.

---

## 2. Prove "best RU ASR" (GigaAM lane, end-to-end)

Run the canonical source (`tinkov-plata.mp4`, the 2h Тиньков sample — see memory
`test-video-samples`) through the real lane. Either trigger a normal upload through
the dashboard, OR hit the endpoint directly with a presigned source URL:

```bash
cd services/ai-worker-python && . .venv/bin/activate
RUN_LIVE=1 \
GIGAAM_ENDPOINT="$GIGAAM_ENDPOINT" \
GIGAAM_WEBHOOK_SECRET="$GIGAAM_WEBHOOK_SECRET" \
WEBHOOK_PUBLIC_URL="https://<webhook-receiver>/gigaam/callback" \
FLIPHOUSE_LIVE_AUDIO_URL="https://<presigned-source-url>" \
python scripts/live_eval.py gigaam
```

The script POSTs `/transcribe`, polls `/status/<id>` to a terminal state, and exits
0 on `succeeded`. The transcript itself is delivered to the **webhook-receiver**
(the signed callback `payload.segments[].words[]` with Cyrillic word timings) — read
it there or in the dashboard. A clean Cyrillic transcript with per-word timings on
the 2h source is the "best RU ASR" proof.

---

## 3. Prove "the cascade beats text-only" (Gemini lane + eval gates)

You need **>=3 real hand-cut clips** with human virality scores. Cut short
vertical webm clips from the source, score each yourself 0-100, and write a
manifest (`clip_path` resolves relative to the manifest's directory):

```json
[
  {"clip_id": "c1", "text": "<transcript of clip 1>", "human_score": 82,
   "clip_path": "clips/c1.webm", "duration_s": 31.5},
  {"clip_id": "c2", "text": "<transcript>", "human_score": 40,
   "clip_path": "clips/c2.webm", "duration_s": 24.0},
  {"clip_id": "c3", "text": "<transcript>", "human_score": 12,
   "clip_path": "clips/c3.webm", "duration_s": 18.0}
]
```

Then run the scorer through BOTH paths and the ratified gates in one command:

```bash
cd services/ai-worker-python && . .venv/bin/activate
RUN_LIVE=1 \
OPENROUTER_API_KEY="sk-or-..." \
FLIPHOUSE_AV_MANIFEST="/abs/path/to/manifest.json" \
python scripts/live_eval.py gemini
```

It prints, per clip: the transcript, the text-only aggregate, the A/V aggregate,
the A/V sub-scores, and the modalities the model actually used. Then it prints:

- `AV EVAL` — the A/V run against the **ratified floors**
  (`RATIFIED_MIN_SPEARMAN=0.7`, `RATIFIED_MIN_DISPERSION=15.0`,
  `RATIFIED_MIN_DIVERGENCE=0.20`). `passed=True` means the A/V path ranks clips
  with human, spreads scores, and its sub-scores discriminate (do not collapse to
  one lockstep signal).
- `CUTOVER` — champion = text-only, challenger = A/V. `promoted=True` (or a
  `reason` explaining the abstain) is the formal "cascade beats text-only"
  decision, with the bootstrap CI on ΔSpearman.

Exit 0 iff the A/V eval passed.

### 3a. Alternative: the guarded pytest live tests

The same proofs exist as opt-in tests (skipped unless the env is set, so they
never touch the CI coverage gate):

```bash
cd services/ai-worker-python && . .venv/bin/activate
FLIPHOUSE_LIVE_GEMINI=1 OPENROUTER_API_KEY=sk-or-... \
FLIPHOUSE_AV_MANIFEST=/abs/path/manifest.json \
python -m pytest tests/scoring/test_live_gemini_eval.py -s -m live
```

`test_live_gemini_smoke_and_eval` runs the seed eval (now including the sub-score
divergence floor); `test_live_gemini_av_beats_text` runs the A/V-vs-text Spearman
comparison + the cutover gate. `-s` prints the calibration lines.

---

## 4. Ratify the floors against a human-labeled set (P2-S7)

The floors in `scoring/eval_runner.py` are **locked numbers** calibrated on the
deterministic seed set. Final ratification confirms they hold on a real
human-labeled set of **15-20 clips** the founder scores in the dashboard:

1. Export the labeled clips to a JSON file in the `dataset.py::load_clips` shape:
   `[{"clip_id": "...", "text": "...", "human_score": 0-100}, ...]`.
2. Load and re-run the gate:
   ```python
   from fliphouse_worker.eval import load_clips
   from fliphouse_worker.scoring import ClipScorer, run_eval
   from fliphouse_worker.llm import OpenRouterAdapter
   clips = load_clips("labeled.json")
   scorer = ClipScorer(OpenRouterAdapter())
   scored = {c.text: scorer.score_clip(c.text) for c in clips}
   report = run_eval(
       lambda t: scored[t].aggregate, clips=clips,
       sub_scores_fn=lambda t: {k: float(v) for k, v in scored[t].sub_scores.items()},
   )
   print(report)
   ```
3. If `report.passed` holds on the human set, the floors graduate from
   "seed-calibrated" to "human-confirmed" — no code change, just evidence. If it
   fails, read the realized `spearman` / `dispersion` / `divergence` and adjust the
   ratified constants with a fresh rationale comment.
