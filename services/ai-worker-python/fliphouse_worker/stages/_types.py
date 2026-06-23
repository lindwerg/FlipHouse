"""StageDeps — the injected-seam bundle every handler receives.

Each impure boundary a handler touches (R2, ffmpeg, the transcription provider,
the scoring cascade, the renderer) is a field here so the unit suite drives a
handler with fakes and reaches 100%. The DEFAULTS are the real wiring (env-built
clients, subprocess ffmpeg, network models); their bodies are ``# pragma: no
cover`` and exercised by the live/integration suite — only the marshalling logic
in the handlers is unit-covered.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..clipping.render import render_vertical_clips
from ..video_asserts import probe_dimensions, probe_duration_seconds

if TYPE_CHECKING:  # heavy/typing-only imports kept off the import path
    from ..clipping.render import RenderManifest
    from ..engine.cascade import CascadeResult
    from ..transcription import Transcript

# Seam signatures for the caption stage (burn ffmpeg + ffprobe + atomic promote).
CaptionBurnFn = Callable[[Path, str, Path], None]
ProbeFn = Callable[[Path], "tuple[int, int]"]
ReplaceFn = Callable[[Path, Path], None]
# Source-duration probe (ffprobe) — the billable quantity for PAYG, in seconds.
ProbeDurationFn = Callable[[Path], float]


def _default_caption_burn(src: Path, ass_text: str, out: Path) -> None:  # pragma: no cover - ffmpeg
    """Burn the ASS into the reframed clip via the LGPL-clean ffmpeg pass."""
    from ..captioning.burn import _run_caption_burn

    _run_caption_burn(src, ass_text, out)


# ffmpeg timeout ceiling for a whole-source pass (proxy transcode / audio extract).
# Generous — these run on the full upload, not a clip; the pragma'd seams below own it.
_FULL_PASS_TIMEOUT_S = 4 * 60 * 60

# Proxy transcode encoder knobs (ASK #6 Speed). The 720p proxy is an INTERNAL
# intermediate (input to asr/score/reframe), NEVER delivered, so it may use GPL
# libx264 — founder-approved for commercial use. ``-preset veryfast`` + ``-threads
# 0`` cut the single longest CPU step (the whole-source 2h pass) by a large factor;
# x264 ``-crf`` gives constant quality at the proxy resolution. The DELIVERY render
# (clipping/render.py) and caption burn STAY libopenh264 — the LGPL invariant on
# delivered clips is load-bearing (render_preflight + golden) and untouched here.
_PROXY_VIDEO_CODEC = "libx264"
_PROXY_PRESET = "veryfast"
_PROXY_CRF = "23"


def _build_transcode_argv(src: Path, out: Path) -> list[str]:
    """Pure argv for the 720p proxy: GPL x264 ``veryfast`` + ``-threads 0``, AAC, faststart."""
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-y",
        "-i",
        str(src),
        "-vf",
        "scale=-2:720",
        "-c:v",
        _PROXY_VIDEO_CODEC,
        "-preset",
        _PROXY_PRESET,
        "-crf",
        _PROXY_CRF,
        "-threads",
        "0",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _default_transcode_ffmpeg(src: Path, out: Path) -> None:  # pragma: no cover - real ffmpeg
    """Normalize any upload to a 720p H.264(GPL libx264)/AAC ``+faststart`` proxy."""
    subprocess.run(
        _build_transcode_argv(src, out),
        check=True,
        capture_output=True,
        text=True,
        timeout=_FULL_PASS_TIMEOUT_S,
    )


def _default_extract_audio(src: Path, out: Path) -> None:  # pragma: no cover - real ffmpeg
    """Extract 16 kHz mono PCM wav for ASR (no video → fast on a long source)."""
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(src),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "16000",
            "-c:a",
            "pcm_s16le",
            str(out),
        ],
        check=True,
        capture_output=True,
        text=True,
        timeout=_FULL_PASS_TIMEOUT_S,
    )


_INLINE_ASR_DISABLED = (
    "inline ASR is unavailable — GigaAM-v3 is the sole engine and runs only on the "
    "GPU submit-and-park lane (Node executeAsr → Modal → asr-finalize). Enable it "
    "with GPU_ASR_ENABLED=true; there is no CPU/whisper fallback."
)


def _default_transcribe(audio_path: Path, params: dict) -> Transcript:
    """Refuse loudly: the inline asr path has no engine (GigaAM is GPU-only).

    GigaAM-v3 is submitted from the Node side via the submit-and-park webhook lane
    and finalized by the ``asr-finalize`` CLI subcommand. There is no inline ASR
    engine to fall back to, so a deploy that reaches this seam (GPU_ASR_ENABLED
    off) must FAIL LOUD rather than silently produce text.
    """
    raise RuntimeError(_INLINE_ASR_DISABLED)


def _default_score_clips(  # pragma: no cover - real OpenRouter network + ffmpeg signals
    transcript: dict, src_path: str, params: dict
) -> CascadeResult:
    """Build the real cascade (OpenRouter adapter + linear segmenter + ClipScorer) and run it.

    ASK #5: candidates come from the deterministic in-order ``linear_segments`` (not
    the LLM cherry-pick), and selection is gated by ``CLIP_QUALITY_THRESHOLD`` (env,
    default ``DEFAULT_QUALITY_THRESHOLD``) — emit every moment over the bar, not a
    fixed k. Tier defaults to BALANCE so native A/V lands on the top finalists.
    """
    from ..engine import linear_segments
    from ..engine.cascade import DEFAULT_QUALITY_THRESHOLD, select_clips
    from ..engine.rerank import RERANK_SYSTEM_PROMPT, rerank_finalists
    from ..llm import OpenRouterAdapter, Profile
    from ..scoring import ClipScorer, resolve_tier

    adapter = OpenRouterAdapter()
    scorer = ClipScorer(adapter)
    tier = resolve_tier()  # SCORING_TIER env → TierConfig, default BALANCE (finalists)
    threshold = float(os.environ.get("CLIP_QUALITY_THRESHOLD", DEFAULT_QUALITY_THRESHOLD))

    def recall_fn(t: dict, signals: object) -> tuple:
        return linear_segments(t, signals, word_segments=params.get("word_segments", ()))

    def rank_fn(prompt: str) -> str:
        # Comparative re-rank uses the cheap SCORING route at temperature 0; the
        # rerank module is fail-open, so an empty/garbled reply keeps the order.
        return adapter.complete(
            profile=Profile.SCORING, system=RERANK_SYSTEM_PROMPT, user=prompt, temperature=0.0
        ).text

    def rerank_fn(survivors: list) -> list:
        return rerank_finalists(survivors, rank_fn=rank_fn)

    return select_clips(
        transcript,
        src_path,
        recall_fn=recall_fn,
        scorer=scorer,
        quality_threshold=threshold,
        tier=tier,
        _rerank_fn=rerank_fn,
    )


@dataclass(frozen=True)
class StageDeps:
    """Every impure boundary a handler touches, injected for 100% unit coverage."""

    r2: object  # R2Client (the only network seam); FakeR2 in tests
    transcode_ffmpeg: Callable[[Path, Path], None] = _default_transcode_ffmpeg
    # ffprobe source duration (seconds) — the PAYG billable quantity, probed in transcode.
    probe_duration: ProbeDurationFn = field(default=probe_duration_seconds)
    extract_audio: Callable[[Path, Path], None] = _default_extract_audio
    transcribe: Callable[[Path, dict], Transcript] = _default_transcribe
    score_clips: Callable[[dict, str, dict], CascadeResult] = _default_score_clips
    render: Callable[..., RenderManifest] = field(default=render_vertical_clips)
    # caption stage seams: burn ffmpeg, ffprobe dimensions, atomic file promote.
    caption_burn: CaptionBurnFn = _default_caption_burn
    probe: ProbeFn = field(default=probe_dimensions)
    replace: ReplaceFn = field(default=os.replace)
