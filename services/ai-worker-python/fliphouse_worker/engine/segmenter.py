"""Linear segmenter (P2 ASK #5): walk the transcript IN ORDER into clip windows.

Replaces the LLM cherry-pick recall as the candidate source. Instead of asking
an LLM for the "top highlights" (out of order, with gaps), this deterministically
splits the WHOLE timeline 0..duration into contiguous, gap-aware, non-overlapping
windows inside a target clip-duration band, snaps each to natural speech edges
via the SHARED ``refine_boundaries`` (reused from recall.py — no second snapper),
and emits a ``CandidateClip`` per window. Every window then flows through the
exact same text/AV scoring; the cascade's threshold gate (not k) decides which
survive. Count therefore scales with content/length, not a fixed quota.

A window breaks at a transcript gap (next segment starts ``gap_s`` after the
current run ends — a real topic/scene boundary) OR when adding the next segment
would push the run past ``target_max_s``. A trailing run shorter than
``target_min_s`` is dropped (a sub-floor stub is not a clip). Pure & immutable.
"""

from __future__ import annotations

from collections.abc import Sequence

from ..dsp import LocalSignals
from .recall import (
    MAX_CLIP_S,
    MIN_CLIP_S,
    CandidateClip,
    _excerpt,
    _flatten_words,
    dsp_prior_score,
    refine_boundaries,
)

# Target clip-duration band. Kept strictly inside refine_boundaries'
# [MIN_CLIP_S, MAX_CLIP_S] so a snap never reverts for being out of range.
TARGET_MIN_S = max(MIN_CLIP_S, 30.0)  # below this a window is a sub-floor stub → dropped
TARGET_MAX_S = min(MAX_CLIP_S, 90.0)  # a contiguous run is flushed before exceeding this
SEGMENT_GAP_S = 1.5  # a transcript gap this long marks a topic/scene boundary → break
_TITLE_WORD_CAP = 8  # how many leading words become the window title


def _window_title(segments: Sequence[dict]) -> str:
    """First few words of a window's first (non-empty) segment → a short human title."""
    words = segments[0].get("text", "").split()
    return " ".join(words[:_TITLE_WORD_CAP]).strip()


def _flush(
    run: Sequence[dict],
    transcript: dict,
    signals: LocalSignals,
    words: Sequence[dict],
    duration: float,
    target_min_s: float,
) -> CandidateClip | None:
    """Snap a non-empty run to speech edges and build a CandidateClip, or None if too short."""
    raw_start = float(run[0]["start"])
    raw_end = float(run[-1]["end"])
    if raw_end - raw_start < target_min_s:
        return None
    start, end = refine_boundaries(raw_start, raw_end, words, signals.pauses, duration)
    return CandidateClip(
        title=_window_title(run),
        start_time=start,
        end_time=end,
        llm_score=0.0,
        dsp_prior=dsp_prior_score(start, end, signals),
        text_excerpt=_excerpt(transcript, start, end),
    )


def _should_break(run: Sequence[dict], seg: dict, gap_s: float, target_max_s: float) -> bool:
    """True when ``seg`` cannot extend the current ``run`` (gap, or would exceed the band)."""
    prev_end = float(run[-1]["end"])
    if float(seg["start"]) - prev_end >= gap_s:
        return True
    return float(seg["end"]) - float(run[0]["start"]) > target_max_s


def linear_segments(
    transcript: dict,
    signals: LocalSignals,
    *,
    word_segments: Sequence[dict] = (),
    target_min_s: float = TARGET_MIN_S,
    target_max_s: float = TARGET_MAX_S,
    gap_s: float = SEGMENT_GAP_S,
) -> tuple[CandidateClip, ...]:
    """Transcript walked IN ORDER → contiguous, gap-aware, snapped candidate windows.

    Accumulates transcript segments into a run; flushes the run (and starts a new
    one) whenever the next segment opens a ``gap_s`` gap or would push the run past
    ``target_max_s``. Each flushed run >= ``target_min_s`` is snapped via the shared
    ``refine_boundaries`` and emitted as a ``CandidateClip`` in timeline order.
    """
    segments = transcript.get("segments") or ()
    if not segments:
        return ()

    duration = float(transcript.get("duration", 0.0))
    words = _flatten_words(word_segments)
    clips: list[CandidateClip] = []
    run: list[dict] = []
    for seg in segments:
        if run and _should_break(run, seg, gap_s, target_max_s):
            clip = _flush(run, transcript, signals, words, duration, target_min_s)
            if clip is not None:
                clips.append(clip)
            run = []
        run.append(seg)
    tail = _flush(run, transcript, signals, words, duration, target_min_s)
    if tail is not None:
        clips.append(tail)
    return tuple(clips)
