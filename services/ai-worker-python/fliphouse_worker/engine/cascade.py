"""Cascade orchestrator (P2-S5): Stage 0 → Stage A recall → Stage B precision.

A thin coordinator that wires the three stages, all dependency-injected (mirrors
the existing ``llm_fn`` seam): ``_signals_fn`` extracts Stage 0 DSP signals,
``recall_fn`` is the (llm_fn-bound) Stage A recall, and ``scorer`` is the Stage B
``ClipScorer`` — text-only in S5 (native A/V is S6). Stage B re-scores each
recall candidate per the rubric; results sort by the precise aggregate, get a
strict final dedupe, and the top-k survive.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..dsp import LocalSignals, extract_local_signals
from ..scoring import ClipScorer, ScoredClip
from .recall import CandidateClip

FINAL_DEDUPE_OVERLAP = 0.50  # strict overlap suppression at the output boundary

RecallFn = Callable[[dict, LocalSignals], tuple[CandidateClip, ...]]


@dataclass(frozen=True)
class SelectedClip:
    """A final ranked clip: its recall candidate, its precise Stage B score, and rank."""

    candidate: CandidateClip
    scored: ScoredClip
    rank: int


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
) -> tuple[SelectedClip, ...]:
    """Run the full cascade → top-``k`` ranked clips (precision-scored, strict-deduped)."""
    signals = _signals_fn(src_path)
    candidates = recall_fn(transcript, signals)
    if not candidates:
        return ()

    scored = [
        SelectedClip(
            candidate=cand,
            scored=scorer.score_clip(cand.text_excerpt, duration_s=cand.end_time - cand.start_time),
            rank=0,
        )
        for cand in candidates
    ]
    scored.sort(key=lambda s: s.scored.aggregate, reverse=True)
    survivors = _final_dedupe(scored)[:k]
    return tuple(
        SelectedClip(candidate=s.candidate, scored=s.scored, rank=i)
        for i, s in enumerate(survivors)
    )
