"""Stage B per-clip fan-out: cut → native A/V score, in parallel (P2-S6).

Each recall candidate is cut to a WebM clip and scored by the multimodal
``ClipScorer``; the calls are I/O-bound network round-trips, so a small
``ThreadPoolExecutor`` runs them concurrently (the whole adapter stack is sync —
asyncio would buy nothing here at a ~3-12 batch and force an AsyncOpenAI rewrite).

Fail-closed, never silently lose a paid clip: a cut-or-A/V failure falls back to
that clip's TEXT-only score (``used_video=False``); only if the text fallback
ALSO fails is the clip dropped (and counted in a per-batch warning). The catch is
broad because the adapter escapes ``RuntimeError`` (402 / retries exhausted) and
``openai.APIError`` (4xx/5xx), which no narrow tuple would cover.

``_threadpool_map`` is the injectable seam: tests pass a serial map so no threads
spawn and coverage stays deterministic.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import TypeVar

from ..clipping import CLIP_VIDEO_MIME, cut_clip
from ..scoring import ClipScorer, ScoredClip
from .recall import CandidateClip

logger = logging.getLogger(__name__)

MAX_SCORE_WORKERS = 6  # cap concurrent calls to one provider (S7 may make this a tier knob)

T = TypeVar("T")
R = TypeVar("R")
CutFn = Callable[[str, float, float], bytes]
MapFn = Callable[[Callable[[T], R], Sequence[T]], list[R]]


@dataclass(frozen=True)
class ClipScore:
    """A candidate's Stage B result and whether it was scored with video."""

    candidate: CandidateClip
    scored: ScoredClip
    used_video: bool


def _isolated(fn: Callable[[T], R], item: T) -> R | None:
    """Run ``fn(item)``; an unanticipated crash is contained to ``None`` (defence-in-depth)."""
    try:
        return fn(item)
    except Exception:
        logger.warning("clip task crashed; dropping", exc_info=True)
        return None


def _threadpool_map(fn: Callable[[T], R], items: Sequence[T]) -> list[R | None]:
    """Map ``fn`` over ``items`` concurrently, preserving input order. Empty → ``[]``."""
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(MAX_SCORE_WORKERS, len(items))) as ex:
        return list(ex.map(lambda it: _isolated(fn, it), items))


def _score_one(
    cand: CandidateClip, scorer: ClipScorer, src: str, cut_fn: CutFn
) -> ClipScore | None:
    """Cut + A/V score one candidate; fall back to text, then drop. Never raises."""
    duration = cand.end_time - cand.start_time
    try:
        video = cut_fn(src, cand.start_time, cand.end_time)
        scored = scorer.score_clip(
            cand.text_excerpt, duration_s=duration, video=video, video_mime=CLIP_VIDEO_MIME
        )
        return ClipScore(candidate=cand, scored=scored, used_video=True)
    except Exception:
        logger.warning(
            "A/V scoring failed for clip [%s, %s]; falling back to text-only",
            cand.start_time,
            cand.end_time,
            exc_info=True,
        )
    try:
        scored = scorer.score_clip(cand.text_excerpt, duration_s=duration)
        return ClipScore(candidate=cand, scored=scored, used_video=False)
    except Exception:
        logger.warning(
            "both modalities failed for clip [%s, %s]; dropping",
            cand.start_time,
            cand.end_time,
            exc_info=True,
        )
        return None


def score_candidates(
    candidates: Sequence[CandidateClip],
    scorer: ClipScorer,
    src: str,
    *,
    cut_fn: CutFn = cut_clip,
    _map_fn: MapFn = _threadpool_map,
) -> list[ClipScore]:
    """Score every candidate (parallel cut→A/V, fail-closed to text) → surviving ClipScores."""
    results = _map_fn(lambda cand: _score_one(cand, scorer, src, cut_fn), candidates)
    survivors = [r for r in results if r is not None]
    dropped = len(results) - len(survivors)
    if dropped:
        logger.warning("%d clip(s) dropped — see preceding per-clip warnings", dropped)
    return survivors
