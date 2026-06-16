"""Cascade orchestrator (P2-S6): Stage 0 → Stage A recall → Stage B precision.

A thin coordinator that wires the three stages, all dependency-injected (mirrors
the existing ``llm_fn`` seam): ``_signals_fn`` extracts Stage 0 DSP signals,
``recall_fn`` is the (llm_fn-bound) Stage A recall, and ``scorer`` is the Stage B
``ClipScorer``. Stage B (S6) now cuts each candidate to a short WebM clip and
re-scores it with NATIVE A/V (default Ideal tier = gemini-3.5-flash), in parallel
and fail-closed to text-only per clip (``_score_fn`` → ``score_candidates``).
Results sort by the precise aggregate, get a strict final dedupe, top-k survive.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..clipping import cut_clip
from ..dsp import LocalSignals, extract_local_signals
from ..scoring import ClipScorer, ScoredClip
from .recall import CandidateClip
from .scoring_fanout import ClipScore, CutFn, score_candidates

FINAL_DEDUPE_OVERLAP = 0.50  # strict overlap suppression at the output boundary

RecallFn = Callable[[dict, LocalSignals], tuple[CandidateClip, ...]]
ScoreFn = Callable[..., list[ClipScore]]


@dataclass(frozen=True)
class SelectedClip:
    """A final ranked clip: its recall candidate, precise Stage B score, rank, modality."""

    candidate: CandidateClip
    scored: ScoredClip
    rank: int
    used_video: bool = True


def _final_dedupe(
    clips: list[SelectedClip], overlap: float = FINAL_DEDUPE_OVERLAP
) -> list[SelectedClip]:
    """Drop a clip overlapping >``overlap`` of the SHORTER span with a higher-scoring kept clip.

    The shorter-span denominator suppresses a long clip that fully contains a kept
    short clip (a one-sided ratio would wrongly let the container survive).
    """
    kept: list[SelectedClip] = []
    for clip in clips:
        c = clip.candidate
        span = c.end_time - c.start_time
        clashes = False
        for k in kept:
            kc = k.candidate
            inter = min(c.end_time, kc.end_time) - max(c.start_time, kc.start_time)
            shorter = min(span, kc.end_time - kc.start_time)
            if inter > 0 and inter > overlap * shorter:
                clashes = True
                break
        if not clashes:
            kept.append(clip)
    return kept


def select_clips(
    transcript: dict,
    src_path: str,
    *,
    recall_fn: RecallFn,
    scorer: ClipScorer,
    k: int = 3,
    _signals_fn: Callable[[str], LocalSignals] = extract_local_signals,
    _cut_fn: CutFn = cut_clip,
    _score_fn: ScoreFn = score_candidates,
) -> tuple[SelectedClip, ...]:
    """Run the full cascade → top-``k`` ranked clips (native-A/V scored, strict-deduped)."""
    signals = _signals_fn(src_path)
    candidates = recall_fn(transcript, signals)
    if not candidates:
        return ()

    clip_scores = _score_fn(candidates, scorer, src_path, cut_fn=_cut_fn)
    scored = [
        SelectedClip(candidate=cs.candidate, scored=cs.scored, rank=0, used_video=cs.used_video)
        for cs in clip_scores
    ]
    scored.sort(key=lambda s: s.scored.aggregate, reverse=True)
    survivors = _final_dedupe(scored)[:k]
    return tuple(
        SelectedClip(candidate=s.candidate, scored=s.scored, rank=i, used_video=s.used_video)
        for i, s in enumerate(survivors)
    )
