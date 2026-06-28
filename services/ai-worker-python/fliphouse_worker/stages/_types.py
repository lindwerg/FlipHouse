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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from ..captioning.keywords import KeywordIndexSelector, stopword_keyword_selector
from ..clipping.render import render_vertical_clips
from ..video_asserts import probe_dimensions, probe_duration_seconds

if TYPE_CHECKING:  # heavy/typing-only imports kept off the import path
    from ..captioning.ass import CaptionLine
    from ..clipping.render import RenderManifest
    from ..engine.cascade import CascadeResult
    from ..transcription import Transcript

# P3-A4 — the live look turns on ONLY when this env flag is truthy (mirrors GPU_ASD_ENABLED).
KEYWORD_LLM_ENABLED = "KEYWORD_LLM_ENABLED"


def _gemini_keyword_selector(  # pragma: no cover - real OpenRouter network
    lines: Sequence[CaptionLine],
) -> Sequence[int | None]:
    """LIVE keyword selector: one batched OpenRouter/Gemini call per clip, fail-open."""
    from ..captioning.keywords import build_gemini_keyword_selector
    from ..llm.openrouter_adapter import OpenRouterAdapter
    from ..llm.routes import Profile
    from ..llm.schemas import LINE_KEYWORDS_SCHEMA

    adapter = OpenRouterAdapter()

    def complete_json_fn(*, system: str, user: str) -> object:
        return adapter.complete_json(
            profile=Profile.KEYWORD,
            system=system,
            user=user,
            schema_name="line_keywords",
            schema=LINE_KEYWORDS_SCHEMA,
            temperature=0.0,
        )

    return build_gemini_keyword_selector(complete_json_fn)(lines)


def resolve_keyword_selector(env: Mapping[str, str] | None = None) -> KeywordIndexSelector:
    """Founder gate (mirrors asd_config.load): the LIVE Gemini selector only when
    ``KEYWORD_LLM_ENABLED`` is truthy, else the PURE stopword heuristic. ``env`` is injectable so
    the unit suite drives it with a plain dict — no real process env, no network."""
    source = os.environ if env is None else env
    flag = str(source.get(KEYWORD_LLM_ENABLED, "")).strip().lower()
    if flag in ("1", "true", "yes"):
        return _gemini_keyword_selector
    return stopword_keyword_selector


# Seam signatures for the caption stage (ffprobe dimensions + atomic promote). SPD-1
# retired the caption-burn ffmpeg seam — captions are folded into the reframe encode.
ProbeFn = Callable[[Path], "tuple[int, int]"]
ReplaceFn = Callable[[Path, Path], None]
# Source-duration probe (ffprobe) — the billable quantity for PAYG, in seconds.
ProbeDurationFn = Callable[[Path], float]


# ffmpeg timeout ceiling for a whole-source pass (proxy transcode / audio extract).
# Generous — these run on the full upload, not a clip; the pragma'd seams below own it.
_FULL_PASS_TIMEOUT_S = 4 * 60 * 60

# Proxy transcode encoder knobs (ASK #6 Speed / SPD-3). The 720p proxy is an INTERNAL
# intermediate (input to asr/score/reframe), NEVER delivered, so it may use GPL
# libx264 — founder-approved for commercial use. SPD-3: the proxy is the single longest
# serial CPU step (the whole-source 2 h pass), and its visual quality barely matters —
# ASR reads only the audio, the LLM video-scoring re-cuts finalists to its OWN tiny
# 480p clip, and the reframe geometry/cropdetect tolerate a softer proxy. So the default
# preset drops to ``superfast`` and ``-crf`` rises to ``26`` to cut wall-clock further;
# ``-threads 0`` lets x264 use every vCPU. All three are env-overridable so the box can be
# re-tuned without a deploy (e.g. FH_PROXY_PRESET=ultrafast on a busier worker). The
# DELIVERY render (clipping/render.py) STAYS libopenh264 — the LGPL invariant on delivered
# clips is load-bearing (render_preflight + golden) and untouched here.
_PROXY_VIDEO_CODEC = "libx264"
_PROXY_PRESET = os.environ.get("FH_PROXY_PRESET", "superfast")
_PROXY_CRF = os.environ.get("FH_PROXY_CRF", "26")
_PROXY_THREADS = os.environ.get("FH_PROXY_THREADS", "0")


def _build_transcode_argv(src: Path, out: Path) -> list[str]:
    """Pure argv for the 720p proxy: GPL x264 (env preset/crf/threads), AAC, faststart."""
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
        _PROXY_THREADS,
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
    """Build the real cascade (OpenRouter adapter + phrase-anchored recall + ClipScorer).

    Recall asks the LLM for highlights whose ``end_phrase`` names the LAST WORDS of a
    COMPLETE sentence, then the RapidFuzz ``align_fn`` resolves that verbatim phrase to
    its word-timestamps (``phrase_boundaries``) so the clip END anchors to the finished
    thought — ``refine_boundaries`` only pads/clamps from there, and falls open to the
    pause/discourse sentence-end snapper when no phrase resolves. Selection is gated by
    ``CLIP_QUALITY_THRESHOLD``
    (env, default ``DEFAULT_QUALITY_THRESHOLD``) — emit every moment over the bar, not a
    fixed k. Tier defaults to BALANCE so native A/V lands on the top finalists.
    """
    from ..engine.cascade import DEFAULT_QUALITY_THRESHOLD, select_clips
    from ..engine.production_recall import build_phrase_anchored_recall_fn
    from ..engine.rerank import build_av_aware_rank_fn, rerank_finalists
    from ..llm import OpenRouterAdapter, Profile
    from ..llm.engine_backend import EngineHighlightBackend, EngineLLMBackend
    from ..scoring import AvScope, ClipScorer, resolve_tier
    from ..scoring.threshold_calibration import resolve_target_percentile

    adapter = OpenRouterAdapter()
    scorer = ClipScorer(adapter)
    tier = resolve_tier()  # SCORING_TIER env → TierConfig, default BALANCE (finalists)
    threshold = float(os.environ.get("CLIP_QUALITY_THRESHOLD", DEFAULT_QUALITY_THRESHOLD))
    # RANK-2: the threshold is calibrated to THIS run's normalized distribution
    # (top (100-P)%), removing the duration-floor crutch. Setting CLIP_QUALITY_THRESHOLD
    # explicitly switches back to the absolute-cut mode (target_percentile=None).
    use_percentile = "CLIP_QUALITY_THRESHOLD" not in os.environ
    target_percentile = resolve_target_percentile() if use_percentile else None
    # phrase_boundaries goes LIVE here: the recall_fn the cascade calls resolves the
    # LLM's verbatim complete-sentence end_phrase to its word span (RapidFuzz align_fn)
    # so the clip END anchors to a finished thought, not the model's noisy float.
    # NOTE: no punct_fn is passed (it stays None). The sentence-end signal is GigaAM-v3's
    # OWN punctuation, projected onto the word stream in transcription/normalize.py
    # (TRANS-1/TRANS-2) — a separate RU punctuation model would be redundant and would
    # pull weights into the pure worker package.
    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=EngineLLMBackend(adapter),
        highlight_fn=EngineHighlightBackend(adapter),
        word_segments=params.get("word_segments", ()),
    )

    # RANK-3: the FINAL comparative re-rank routes through an A/V-AWARE judge for the
    # tiers that actually gathered A/V (Баланс/Идеал → OFFER_MATCH) so the published
    # order does not discard the A/V signal; Бюджет (text-only) stays on SCORING. The
    # one extra call on ≤10 clips is cheap, and rerank_finalists is fail-open.
    av_aware = tier.av_scope is not AvScope.NONE

    def complete_fn(*, profile: Profile, system: str, user: str, temperature: float) -> str:
        return adapter.complete(
            profile=profile, system=system, user=user, temperature=temperature
        ).text

    rank_fn = build_av_aware_rank_fn(complete_fn, av_aware=av_aware)

    def rerank_fn(survivors: list) -> list:
        return rerank_finalists(survivors, rank_fn=rank_fn)

    return select_clips(
        transcript,
        src_path,
        recall_fn=recall_fn,
        scorer=scorer,
        quality_threshold=threshold,
        target_percentile=target_percentile,
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
    # caption stage seams: ffprobe dimensions, atomic file promote. SPD-1 retired the
    # caption-burn seam (captions now ride the reframe encode); `probe` stays for parity
    # + any future dimension check on the forwarded clips.
    probe: ProbeFn = field(default=probe_dimensions)
    replace: ReplaceFn = field(default=os.replace)
    # P3-A4 keyword selector. PURE default (no network, no env read on ANY default path);
    # production bootstrap overrides with resolve_keyword_selector(os.environ) so the live
    # Gemini look is opt-in (KEYWORD_LLM_ENABLED), never auto-armed by preset selection.
    keyword_selector: KeywordIndexSelector = stopword_keyword_selector
