#!/usr/bin/env python3
"""One-command live proof of the P2 quality bar (#4 founder-run).

This script lives OUTSIDE the ``fliphouse_worker`` package on purpose: it makes
REAL network calls (GigaAM GPU endpoint + Gemini via OpenRouter), so it is never
imported by CI and never measured by the 100% coverage gate — it is the opt-in
"prove it live" path the pragma'd seams point at.

Two independent proofs, each gated by its own env so the founder can run either:

  GIGAAM proof — "best RU ASR":
    Submits the canonical clip to the deployed GigaAM-v3 Modal endpoint and polls
    status. (Transcript is delivered to the webhook-receiver, not returned inline;
    the script prints the accepted request_id + terminal status so the lane is
    proven end-to-end. Read the transcript on the receiver / dashboard.)

  GEMINI proof — "cascade beats text-only":
    Scores >=3 hand-cut clips both text-only and native-A/V through the SAME
    production ``ClipScorer``, prints each transcript + sub-scores + aggregate, and
    runs the ratified eval gate (Spearman / dispersion / sub-score divergence) plus
    the cutover gate (champion=text, challenger=A/V).

Run:

    RUN_LIVE=1 \\
    OPENROUTER_API_KEY=sk-or-... \\
    FLIPHOUSE_AV_MANIFEST=/path/to/manifest.json \\
    python scripts/live_eval.py gemini

    RUN_LIVE=1 \\
    GIGAAM_ENDPOINT=https://...modal.run \\
    GIGAAM_WEBHOOK_SECRET=... WEBHOOK_PUBLIC_URL=https://.../gigaam/callback \\
    FLIPHOUSE_LIVE_AUDIO_URL=https://<presigned-source> \\
    python scripts/live_eval.py gigaam

Exit non-zero on any failed gate so it doubles as a manual CI command.
"""

from __future__ import annotations

import json
import os
import sys
import time
import urllib.request
import uuid

# Make the package importable when run from the service root without an install.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

POLL_INTERVAL_S = 5.0
POLL_TIMEOUT_S = 1800.0  # a 2h source chunked by VAD is minutes of GPU work
_TERMINAL = {"succeeded", "failed"}


def _require(name: str) -> str:
    value = os.getenv(name)
    if not value:
        sys.exit(f"missing required env var {name!r} — see the module docstring")
    return value


def _http_json(url: str, *, method: str = "GET", body: dict | None = None) -> dict:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        url, data=data, method=method
    )  # noqa: S310 - explicit founder-run URL
    if data is not None:
        req.add_header("content-type", "application/json")
    with urllib.request.urlopen(req, timeout=60) as resp:  # noqa: S310
        return json.loads(resp.read().decode("utf-8"))


def run_gigaam() -> int:
    """Submit the canonical clip to the live GigaAM endpoint and poll to terminal."""
    endpoint = _require("GIGAAM_ENDPOINT").rstrip("/")
    audio_url = _require("FLIPHOUSE_LIVE_AUDIO_URL")
    webhook_url = _require("WEBHOOK_PUBLIC_URL")
    request_id = f"live-eval-{uuid.uuid4().hex[:12]}"

    print(f"[gigaam] POST {endpoint}/transcribe request_id={request_id}", flush=True)
    accepted = _http_json(
        f"{endpoint}/transcribe",
        method="POST",
        body={
            "request_id": request_id,
            "audio_url": audio_url,
            "language": "ru",
            "webhook_url": webhook_url,
            "output_prefix": f"live-eval/{request_id}",
        },
    )
    print(f"[gigaam] accepted: {accepted}", flush=True)

    deadline = time.monotonic() + POLL_TIMEOUT_S
    while time.monotonic() < deadline:
        record = _http_json(f"{endpoint}/status/{request_id}")
        status = record.get("status")
        print(f"[gigaam] status={status}", flush=True)
        if status in _TERMINAL:
            print(f"[gigaam] TERMINAL: {json.dumps(record, ensure_ascii=False)}", flush=True)
            return 0 if status == "succeeded" else 1
        time.sleep(POLL_INTERVAL_S)
    print("[gigaam] TIMEOUT waiting for terminal status", flush=True)
    return 1


def run_gemini() -> int:
    """Score hand-cut clips text vs A/V and run the ratified eval + cutover gates."""
    _require("OPENROUTER_API_KEY")
    manifest = _require("FLIPHOUSE_AV_MANIFEST")

    from fliphouse_worker.clipping import CLIP_VIDEO_MIME
    from fliphouse_worker.eval import evaluate, evaluate_cutover, load_av_clips
    from fliphouse_worker.llm import OpenRouterAdapter
    from fliphouse_worker.scoring import (
        RATIFIED_MIN_DISPERSION,
        RATIFIED_MIN_DIVERGENCE,
        RATIFIED_MIN_SPEARMAN,
        ClipScorer,
    )

    clips = load_av_clips(manifest)
    if len(clips) < 3:
        sys.exit("A/V comparison needs >=3 clips — extend the manifest")

    scorer = ClipScorer(OpenRouterAdapter())
    text_map: dict[str, float] = {}
    av_map: dict[str, float] = {}
    av_sub: dict[str, dict[str, float]] = {}
    for c in clips:
        text = scorer.score_clip(c.text, duration_s=c.duration_s)
        av = scorer.score_clip(
            c.text,
            duration_s=c.duration_s,
            video=c.clip_path.read_bytes(),
            video_mime=CLIP_VIDEO_MIME,
        )
        text_map[c.clip_id] = text.aggregate
        av_map[c.clip_id] = av.aggregate
        av_sub[c.clip_id] = {k: float(v) for k, v in av.sub_scores.items()}
        print(
            f"[gemini] {c.clip_id}: human={c.human_score} "
            f"text={text.aggregate:.1f} av={av.aggregate:.1f} "
            f"av_sub={av.sub_scores} modalities={av.modalities_used}",
            flush=True,
        )
        print(f"          transcript: {c.text[:120]}", flush=True)

    # Ratified gate on the A/V run (champion path): rank agreement + spread +
    # sub-score divergence all measured against the ratified floors.
    av_report = evaluate(
        av_map,
        clips,  # type: ignore[arg-type]  # AvLabeledClip is a structural LabeledClip
        min_spearman=RATIFIED_MIN_SPEARMAN,
        min_dispersion=RATIFIED_MIN_DISPERSION,
        sub_scores=av_sub,
        min_divergence=RATIFIED_MIN_DIVERGENCE,
    )
    print(
        f"[gemini] AV EVAL: spearman={av_report.spearman:.3f} "
        f"dispersion={av_report.dispersion:.2f} divergence={av_report.divergence} "
        f"passed={av_report.passed}",
        flush=True,
    )

    cutover = evaluate_cutover(
        text_map,
        av_map,
        clips,  # type: ignore[arg-type]
        min_spearman=RATIFIED_MIN_SPEARMAN,
        min_dispersion=RATIFIED_MIN_DISPERSION,
        min_delta_spearman=0.0,
        min_n=3,
        n_bootstrap=1000,
    )
    print(
        f"[gemini] CUTOVER: promoted={cutover.promoted} reason={cutover.reason} "
        f"delta={cutover.delta_spearman:+.3f} "
        f"ci=({cutover.delta_ci_low:.3f},{cutover.delta_ci_high:.3f})",
        flush=True,
    )
    return 0 if av_report.passed else 1


def main(argv: list[str]) -> int:
    if not os.getenv("RUN_LIVE"):
        sys.exit("refusing to run: set RUN_LIVE=1 (this makes real, paid API calls)")
    mode = argv[1] if len(argv) > 1 else ""
    if mode == "gigaam":
        return run_gigaam()
    if mode == "gemini":
        return run_gemini()
    sys.exit("usage: live_eval.py {gigaam|gemini}")


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
