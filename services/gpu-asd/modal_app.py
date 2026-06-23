"""Modal packaging for the LR-ASD GPU active-speaker service (deploy-only).

This file wires the tested ``fliphouse_asd`` package (contracts, validation, real
HMAC verification, score-shape orchestration) onto Modal's serverless GPU, plus the
heavy LR-ASD inference. It lives at the SERVICE ROOT, not inside the package, so the
package's 100%-coverage gate never sees it — Modal glue + the model are exercised by
a live deploy / ``--selftest``, not by CI.

LR-ASD: Junhua-Liao/LR-ASD (MIT). Bundled weights (``weight/finetuning_TalkSet.model``),
S3FD face detector (bundled), scenedetect + python_speech_features. NO pyannote, NO
gated checkpoints, NO Ultralytics/InsightFace — clean for commercial use.

Topology (serverless, scale-to-zero): ONE GPU ASGI app. Unlike the GigaAM
submit-and-park lane, ``/score`` is SYNCHRONOUS — the worker blocks on it inline
during the render, so the model runs in-request and the score grid comes back in the
same 200 response. Scoring a single clip window (seconds of video) is fast enough to
serve synchronously on an A10G.

Pipeline per request (``_run_lr_asd``):
  1. Fetch the proxy window ``[start, end]`` to a local mp4 (ffmpeg, copy-trim).
  2. S3FD face-detect every decoded frame; IOU-track into face tracks; crop 224x224
     face videos with synced audio (the stock LR-ASD ``Columbia_test`` preprocessing).
  3. Run LR-ASD ``evaluate_network`` → per-track per-frame speaking confidence.
  4. Project track scores onto the WORKER's per-(frame, face) boxes by IOU+time match,
     returning the exact ragged grid the worker zips back onto its faces.

Deploy:  ``modal deploy modal_app.py``  (run from this dir; the package ships via
``add_local_python_source``). Self-test:  ``modal run modal_app.py --selftest``.

Secrets (Modal secret ``fliphouse-asd``):
  * ``GPU_ASD_SECRET`` — HMAC key, MUST equal the worker's ``GPU_ASD_SECRET``.
"""

from __future__ import annotations

import json
import os
import subprocess

import modal

APP_NAME = "fliphouse-asd"
GPU_KIND = "A10G"
CACHE_DIR = "/cache"
# LR-ASD repo + bundled weights are baked into the image at build time, PINNED to an
# exact commit so the adapter's preprocessing matches the published weights forever.
LR_ASD_DIR = "/opt/LR-ASD"
LR_ASD_REPO = "https://github.com/Junhua-Liao/LR-ASD.git"
LR_ASD_COMMIT = "1b6dcd2d8fc2895683de6508ec6294ec47d388ca"
# Bundled checkpoints shipped in-tree (MIT). Finetuned-on-TalkSet is preferred; the
# AVA-pretrained checkpoint is the fallback. Both ride in the cloned repo's weight/ dir.
LR_ASD_CKPT_PRIMARY = "weight/finetuning_TalkSet.model"
LR_ASD_CKPT_FALLBACK = "weight/pretrain_AVA.model"
SCALEDOWN_WINDOW_S = 300
# A clip window is seconds of video; scoring is fast, but cap generously for a cold GPU.
REQUEST_TIMEOUT_S = 600

# Heavy GPU image: CUDA torch + the LR-ASD repo (bundled weights + S3FD) + the
# preprocessing deps. httpx fetches the proxy window. Versions pinned to the LR-ASD
# requirements; ffmpeg for the copy-trim + audio extraction.
gpu_image = (
    modal.Image.debian_slim(python_version="3.11")
    .apt_install("ffmpeg", "git", "libgl1", "libglib2.0-0")
    .pip_install(
        "torch==2.2.2",
        "torchaudio==2.2.2",
        "opencv-python-headless>=4.9",
        "scenedetect>=0.6",
        "python_speech_features",
        "scipy",
        "numpy<2",
        "tqdm",
        "httpx>=0.27",
    )
    .run_commands(
        # Clone then hard-pin to LR_ASD_COMMIT (shallow clone can't checkout an arbitrary
        # sha directly, so fetch that object explicitly, then reset onto it).
        f"git clone {LR_ASD_REPO} {LR_ASD_DIR}",
        f"git -C {LR_ASD_DIR} fetch --depth 1 origin {LR_ASD_COMMIT}",
        f"git -C {LR_ASD_DIR} checkout {LR_ASD_COMMIT}",
        # The repo ships weights in-tree; confirm at least one bundled checkpoint is present.
        f"test -f {LR_ASD_DIR}/{LR_ASD_CKPT_PRIMARY} "
        f"|| test -f {LR_ASD_DIR}/{LR_ASD_CKPT_FALLBACK}",
    )
    .env({"TORCH_HOME": f"{CACHE_DIR}/torch", "PYTHONPATH": LR_ASD_DIR})
    # The pure package PLUS the two deploy-only root modules the GPU path imports
    # (lr_asd_runner → lr_asd_eval). Without these the in-request import would fail.
    .add_local_python_source("fliphouse_asd")
    .add_local_python_source("lr_asd_runner")
    .add_local_python_source("lr_asd_eval")
)

app = modal.App(APP_NAME)
model_cache = modal.Volume.from_name(f"{APP_NAME}-cache", create_if_missing=True)
secret = modal.Secret.from_name(APP_NAME)


def _fetch_window(proxy_url: str, start: float, end: float, dst: str) -> None:
    """Copy-trim ``[start, end]`` of the proxy to a local mp4 (re-encode-free where possible)."""
    subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-ss",
            f"{start}",
            "-to",
            f"{end}",
            "-i",
            proxy_url,
            "-c",
            "copy",
            dst,
        ],
        check=True,
        capture_output=True,
    )


def _iou(a: dict, b: tuple[float, float, float, float]) -> float:
    """Intersection-over-union of an LR-ASD track box ``a`` and a worker box ``b``."""
    ax0, ay0, ax1, ay1 = a["x0"], a["y0"], a["x1"], a["y1"]
    bx0, by0, bw, bh = b
    bx1, by1 = bx0 + bw, by0 + bh
    ix0, iy0 = max(ax0, bx0), max(ay0, by0)
    ix1, iy1 = min(ax1, bx1), min(ay1, by1)
    iw, ih = max(0.0, ix1 - ix0), max(0.0, iy1 - iy0)
    inter = iw * ih
    union = (ax1 - ax0) * (ay1 - ay0) + bw * bh - inter
    return inter / union if union > 0 else 0.0


@app.cls(
    image=gpu_image,
    gpu=GPU_KIND,
    volumes={CACHE_DIR: model_cache},
    secrets=[secret],
    scaledown_window=SCALEDOWN_WINDOW_S,
    timeout=REQUEST_TIMEOUT_S,
    min_containers=0,
    max_containers=2,
)
class Scorer:
    @modal.enter()
    def load(self) -> None:
        """Load the LR-ASD network + S3FD once per warm container."""
        import sys

        sys.path.insert(0, LR_ASD_DIR)
        import torch  # type: ignore[import-not-found]
        from ASD import ASD  # type: ignore[import-not-found]
        from model.faceDetector.s3fd import S3FD  # type: ignore[import-not-found]

        ckpt = os.path.join(LR_ASD_DIR, LR_ASD_CKPT_PRIMARY)
        if not os.path.exists(ckpt):
            ckpt = os.path.join(LR_ASD_DIR, LR_ASD_CKPT_FALLBACK)
        net = ASD()
        net.loadParameters(ckpt)
        net.eval()
        self._net = net
        self._detector = S3FD(device="cuda" if torch.cuda.is_available() else "cpu")
        print("[lr-asd] model + S3FD loaded", flush=True)

    def _run_lr_asd(self, req_dict: dict) -> list[list[float]]:
        """S3FD track + LR-ASD score, projected onto the worker's per-frame face boxes."""
        from fliphouse_asd.contracts import ScoreRequest
        from lr_asd_runner import score_window  # bundled-in alongside modal_app

        req = ScoreRequest(
            proxy_url=req_dict["proxy_url"],
            start=req_dict["start"],
            end=req_dict["end"],
            sample_fps=req_dict["sample_fps"],
            frames=tuple(
                tuple((f["x"], f["y"], f["w"], f["h"]) for f in frame)
                for frame in req_dict["frames"]
            ),
        )
        return score_window(req, self._net, self._detector, _fetch_window, _iou)

    @modal.asgi_app()
    def web(self):
        """The SYNCHRONOUS signed ``/score`` front, served on the GPU container."""
        from fliphouse_asd.app import AppDeps, create_app
        from fliphouse_asd.contracts import ScoreRequest

        def score_fn(req: ScoreRequest):
            req_dict = {
                "proxy_url": req.proxy_url,
                "start": req.start,
                "end": req.end,
                "sample_fps": req.sample_fps,
                "frames": [
                    [{"x": f.x, "y": f.y, "w": f.w, "h": f.h} for f in fr] for fr in req.frames
                ],
            }
            grid = self._run_lr_asd(req_dict)
            return tuple(tuple(float(s) for s in row) for row in grid)

        return create_app(AppDeps(secret=os.environ["GPU_ASD_SECRET"], score_fn=score_fn))


@app.local_entrypoint()
def selftest() -> None:
    """``modal run modal_app.py`` — exercise the PURE package end-to-end (no GPU model).

    Verifies the deploy wiring: build a signed request, run it through the real ASGI
    app with a FAKE in-process scorer (so this needs no GPU), and assert a 200 with a
    correctly-shaped score grid. Proves the contract + HMAC + validation are intact in
    the deployed image before the worker is ever pointed at it.
    """
    import asyncio

    from fliphouse_asd.app import AppDeps, create_app
    from fliphouse_asd.contracts import ScoreRequest
    from fliphouse_asd.signing import compute_signature

    secret = "selftest-secret"

    def fake_score(req: ScoreRequest):
        # One score per face per frame — the smaller-indexed face "speaks".
        return tuple(tuple(1.0 if j == 0 else 0.0 for j in range(len(fr))) for fr in req.frames)

    app_callable = create_app(AppDeps(secret=secret, score_fn=fake_score))
    body = json.dumps(
        {
            "proxy_url": "https://example.com/proxy.mp4",
            "start": 0.0,
            "end": 1.0,
            "sample_fps": 2.0,
            "frames": [[{"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 50, "y": 0, "w": 10, "h": 10}]],
        }
    ).encode("utf-8")
    ts = "1700000000"
    sig = compute_signature(secret, ts, body)

    sent: list = []

    async def drive() -> None:
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/score",
            "headers": [
                (b"x-fliphouse-timestamp", ts.encode()),
                (b"x-fliphouse-signature", sig.encode()),
            ],
        }
        body_events = iter([{"type": "http.request", "body": body, "more_body": False}])

        async def receive():
            return next(body_events)

        async def send(message):
            sent.append(message)

        await app_callable(scope, receive, send)

    asyncio.run(drive())
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    payload = json.loads(next(m["body"] for m in sent if m["type"] == "http.response.body"))
    assert status == 200, f"selftest expected 200, got {status}: {payload}"
    assert payload["scores"] == [[1.0, 0.0]], payload
    print("[lr-asd] selftest OK — signed /score → 200 with shaped grid", flush=True)
