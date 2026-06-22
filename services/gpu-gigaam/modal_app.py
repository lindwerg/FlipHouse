"""Modal packaging for the GigaAM-v3 GPU transcription service (deploy-only).

This file is the ONE founder-gated boundary the skeleton always pointed at: it
wires the tested `fliphouse_gigaam` package (contracts, validation, orchestration,
real HMAC signing) onto Modal's serverless GPU. It lives at the SERVICE ROOT, not
inside the package, so the package's 100%-coverage gate never sees it — Modal glue
is exercised by a live deploy, not by CI.

Topology (serverless, scale-to-zero):

  * ``web``  — a cheap CPU ASGI front. ``POST /transcribe`` validates the body
    (reusing the tested ``parse_submit_request``), marks ``processing`` in a
    cross-container ``modal.Dict``, SPAWNS the GPU job, and returns ``202`` without
    blocking. ``GET /status/<id>`` reads that Dict (the sweep's backstop). This is
    the Modal-native replacement for ``app.py``'s in-process ``schedule`` seam —
    fire-and-forget on Modal must be a real ``.spawn`` to a separate container, not
    an asyncio task that dies when the HTTP response is sent.
  * ``Transcriber`` — an A10G GPU class. ``@modal.enter`` loads ``v3_e2e_rnnt``
    once per warm container; ``run`` builds the real ``TranscribeDeps`` (httpx
    poster + Dict store + the longform→contract adapter) and calls the SAME tested
    ``run_transcription`` orchestration, which fetches the audio, transcribes, and
    POSTs the signed callback to the webhook-receiver.

Deploy:  ``modal deploy modal_app.py``  (run from this dir; the package is
shipped via ``add_local_python_source``).

Secrets (Modal secret ``fliphouse-gigaam``):
  * ``GIGAAM_WEBHOOK_SECRET`` — HMAC key, MUST equal the webhook-receiver's.
  * ``HF_TOKEN`` — HuggingFace token with accepted terms for the gated
    ``pyannote/segmentation-3.0`` VAD that ``transcribe_longform`` needs.
"""

from __future__ import annotations

import json
import os
import subprocess

import modal

APP_NAME = "fliphouse-gigaam"
MODEL_NAME = "v3_e2e_rnnt"
GPU_KIND = "A10G"
CACHE_DIR = "/cache"
# A warm window long enough to reuse the loaded model across back-to-back jobs,
# short enough that an idle GPU costs nothing (scale-to-zero after this).
SCALEDOWN_WINDOW_S = 300
# A 2h source chunked by VAD is minutes of GPU work; cap generously.
JOB_TIMEOUT_S = 3600

# Heavy GPU image: CUDA torch + GigaAM-v3 with the longform (pyannote VAD) extra,
# plus httpx for the audio fetch + signed callback POST. Versions pinned to the
# GigaAM-v3 model-card recommendation.
gpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "libsndfile1")
    .pip_install("torch==2.8.0", "torchaudio==2.8.0", "httpx>=0.27")
    .pip_install("gigaam[longform] @ git+https://github.com/salute-developers/GigaAM.git")
    # Park HF + torch caches on the persisted Volume so cold starts don't re-download
    # the model weights or the gated VAD checkpoint every time.
    .env({"HF_HOME": f"{CACHE_DIR}/hf", "TORCH_HOME": f"{CACHE_DIR}/torch"})
    .add_local_python_source("fliphouse_gigaam")
)

# Slim front image: no torch/model — it only validates, touches the Dict, and spawns.
web_image = modal.Image.debian_slim(python_version="3.11").add_local_python_source(
    "fliphouse_gigaam"
)

app = modal.App(APP_NAME)
model_cache = modal.Volume.from_name(f"{APP_NAME}-cache", create_if_missing=True)
status_dict = modal.Dict.from_name(f"{APP_NAME}-status", create_if_missing=True)
secret = modal.Secret.from_name(APP_NAME)


class _DictStore:
    """A ``status_store``-compatible facade over a ``modal.Dict``.

    The orchestrator only ever calls ``mark_*``; the ``web`` front reads the Dict
    directly for ``GET /status``. Backing the store with a Dict (not the skeleton's
    per-process ``InMemoryStatusStore``) makes status survive container churn and be
    visible to the front even though the job ran on a different GPU container.
    """

    def __init__(self, store: modal.Dict) -> None:
        self._store = store

    def mark_processing(self, request_id: str) -> None:
        self._store[request_id] = {"request_id": request_id, "status": "processing"}

    def mark_succeeded(self, request_id: str) -> None:
        self._store[request_id] = {"request_id": request_id, "status": "succeeded"}

    def mark_failed(self, request_id: str, error: str) -> None:
        self._store[request_id] = {
            "request_id": request_id,
            "status": "failed",
            "error": error,
        }


@app.cls(
    image=gpu_image,
    gpu=GPU_KIND,
    volumes={CACHE_DIR: model_cache},
    secrets=[secret],
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=JOB_TIMEOUT_S,
    min_containers=0,
    max_containers=2,
)
class Transcriber:
    @modal.enter()
    def load(self) -> None:
        """Load GigaAM-v3 once per warm container; persist the weight cache."""
        import gigaam  # type: ignore[import-not-found]

        # HF_TOKEN (gated pyannote VAD) is injected from the Modal secret env and
        # read by gigaam/pyannote via os.environ — no explicit pass-through needed.
        self._model = gigaam.load_model(MODEL_NAME)
        model_cache.commit()

    @modal.method()
    def run(self, req_dict: dict) -> None:
        """Run the tested orchestration for one submit on the GPU container."""
        from fliphouse_gigaam.config import _httpx_poster
        from fliphouse_gigaam.contracts import SubmitRequest
        from fliphouse_gigaam.orchestrator import TranscribeDeps, run_transcription
        from fliphouse_gigaam.transcribe import payload_from_longform

        req = SubmitRequest(**req_dict)
        model = self._model

        def _transcribe(audio_path: str, language: str):
            # The worker presigns the SOURCE container (mp4/mkv/…), and the
            # orchestrator fetches it to an extension-less path. Normalize to a
            # 16 kHz mono WAV with ffmpeg first so GigaAM gets exactly the PCM it
            # expects regardless of source container or missing extension — and so
            # a decoder never has to sniff a no-extension blob.
            wav_path = f"{audio_path}.16k.wav"
            subprocess.run(
                [
                    "ffmpeg",
                    "-nostdin",
                    "-loglevel",
                    "error",
                    "-y",
                    "-i",
                    audio_path,
                    "-vn",
                    "-ac",
                    "1",
                    "-ar",
                    "16000",
                    "-f",
                    "wav",
                    wav_path,
                ],
                check=True,
                capture_output=True,
            )
            # word_timestamps=True → per-word absolute times for caption burn-in.
            result = model.transcribe_longform(wav_path, word_timestamps=True)
            return payload_from_longform(result, language=language)

        deps = TranscribeDeps(
            secret=os.environ["GIGAAM_WEBHOOK_SECRET"],
            poster=_httpx_poster(),
            store=_DictStore(status_dict),
            transcribe_audio=_transcribe,
        )
        run_transcription(req, deps)


async def _read_body(receive) -> bytes:
    chunks: list[bytes] = []
    more = True
    while more:
        event = await receive()
        chunks.append(event.get("body", b""))
        more = event.get("more_body", False)
    return b"".join(chunks)


async def _send_json(send, status: int, body: dict) -> None:
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": raw})


@app.function(
    image=web_image,
    secrets=[secret],
    scaledown_window=SCALEDOWN_WINDOW_S,
    min_containers=0,
)
@modal.asgi_app()
def web():
    """The CPU ASGI front: validate + mark + spawn (202), and serve status/health."""
    from fliphouse_gigaam.contracts import STATUS_ACCEPTED
    from fliphouse_gigaam.errors import InvalidSubmitRequest
    from fliphouse_gigaam.validate import parse_submit_request

    async def asgi(scope, receive, send):
        if scope["type"] != "http":
            return
        method = scope["method"]
        path = scope["path"]

        if method == "POST" and path == "/transcribe":
            try:
                decoded = json.loads(await _read_body(receive))
                req = parse_submit_request(decoded)
            except (InvalidSubmitRequest, json.JSONDecodeError) as exc:
                await _send_json(send, 400, {"error": str(exc)})
                return
            # Mark processing BEFORE the spawn so an immediate GET /status is truthful.
            status_dict[req.request_id] = {
                "request_id": req.request_id,
                "status": "processing",
            }
            Transcriber().run.spawn(
                {
                    "request_id": req.request_id,
                    "audio_url": req.audio_url,
                    "language": req.language,
                    "webhook_url": req.webhook_url,
                    "output_prefix": req.output_prefix,
                }
            )
            await _send_json(send, 202, {"request_id": req.request_id, "status": STATUS_ACCEPTED})
        elif method == "GET" and path.startswith("/status/"):
            request_id = path[len("/status/") :]
            record = status_dict.get(request_id)
            if record is None:
                await _send_json(send, 404, {"error": "unknown request_id"})
            else:
                await _send_json(send, 200, record)
        elif method == "GET" and path == "/health":
            await _send_json(send, 200, {"status": "ok"})
        else:
            await _send_json(send, 404, {"error": "not found"})

    return asgi
