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


def _default_transcode_ffmpeg(src: Path, out: Path) -> None:  # pragma: no cover - real ffmpeg
    """Normalize any upload to a 720p H.264(LGPL libopenh264)/AAC ``+faststart`` proxy."""
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
            "-vf",
            "scale=-2:720",
            "-c:v",
            "libopenh264",
            "-b:v",
            "2M",
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
        ],
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


def _default_transcribe(audio_path: Path, params: dict) -> Transcript:  # pragma: no cover - model
    """Transcribe via the inline CPU fallback (faster-whisper, genuinely-$0 path).

    The GigaAM-v3 GPU primary is NOT submitted from here anymore — it is submitted
    from the Node side via the submit-and-park webhook lane, then finalized by the
    ``asr-finalize`` CLI subcommand. This inline path is the deliberate CPU
    fallback only, so it requests ``prefer='local'``: requesting cloud here with no
    transport would (correctly) raise instead of silently degrading.
    """
    from ..transcription import select_provider

    language = params.get("language", "ru")
    provider = select_provider(
        prefer=params.get("transcription_prefer", "local"), language=language
    )
    return provider.transcribe(str(audio_path), language=language)


def _default_score_clips(  # pragma: no cover - real OpenRouter network + ffmpeg signals
    transcript: dict, src_path: str, params: dict
) -> CascadeResult:
    """Build the real cascade (OpenRouter adapter + reliable recall + ClipScorer) and run it."""
    from ..engine import recall_candidates
    from ..engine.cascade import select_clips
    from ..llm import EngineHighlightBackend, EngineLLMBackend, OpenRouterAdapter
    from ..scoring import ClipScorer

    adapter = OpenRouterAdapter()
    llm_fn = EngineLLMBackend(adapter)
    highlight_fn = EngineHighlightBackend(adapter)
    scorer = ClipScorer(adapter)
    k = int(params.get("k", 3))

    def recall_fn(t: dict, signals: object) -> tuple:
        return recall_candidates(
            t,
            signals,
            llm_fn=llm_fn,
            highlight_fn=highlight_fn,
            word_segments=params.get("word_segments", ()),
            k=k,
        )

    return select_clips(transcript, src_path, recall_fn=recall_fn, scorer=scorer, k=k)


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
