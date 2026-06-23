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

import functools
import logging
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TypeVar

from ..clipping import CLIP_VIDEO_MIME, cut_clip
from ..concurrency import MapFn, ordered_threadpool_map
from ..scoring import ClipScorer, ScoredClip
from ..scoring.tiers import IDEAL, AvScope, TierConfig
from .recall import CandidateClip

logger = logging.getLogger(__name__)

MAX_SCORE_WORKERS = 6  # default cap on concurrent calls to one provider; tier overrides

T = TypeVar("T")
R = TypeVar("R")
CutFn = Callable[[str, float, float], bytes]


@dataclass(frozen=True)
class ClipScore:
    """A candidate's Stage B result and whether it was scored with video."""

    candidate: CandidateClip
    scored: ScoredClip
    used_video: bool


def _threadpool_map(
    fn: Callable[[T], R], items: Sequence[T], max_workers: int = MAX_SCORE_WORKERS
) -> list[R | None]:
    """Scoring's drop-and-continue fan-out — the shared util at this cap (back-compat alias)."""
    return ordered_threadpool_map(fn, items, max_workers=max_workers)


def _want_video_flags(tier: TierConfig, n: int) -> list[bool]:
    """Per-candidate A/V flag from the tier's scope (candidates are recall-ranked desc)."""
    if tier.av_scope is AvScope.NONE:
        return [False] * n
    if tier.av_scope is AvScope.ALL:
        return [True] * n
    return [i < tier.av_finalists_n for i in range(n)]  # FINALISTS: top-N by free recall prior


def _score_one(
    cand: CandidateClip, scorer: ClipScorer, src: str, cut_fn: CutFn, want_video: bool = True
) -> ClipScore | None:
    """Cut + A/V score one candidate; fall back to text, then drop. Never raises.

    ``want_video=False`` (Бюджет / non-finalist) skips the A/V attempt entirely and
    scores text-only, reusing the same fail-closed text path.
    """
    duration = cand.end_time - cand.start_time
    if want_video:
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
    tier: TierConfig = IDEAL,
) -> list[ClipScore]:
    """Score every candidate per the tier's A/V scope (fail-closed to text) → ClipScores."""
    flags = _want_video_flags(tier, len(candidates))
    # The default threadpool gets the tier's worker cap; an injected map (tests)
    # is used verbatim so its seam stays byte-identical.
    map_fn: MapFn = _map_fn
    if map_fn is _threadpool_map:
        map_fn = functools.partial(_threadpool_map, max_workers=tier.max_score_workers)
    results = map_fn(
        lambda pair: _score_one(pair[0], scorer, src, cut_fn, pair[1]),
        list(zip(candidates, flags, strict=True)),
    )
    survivors = [r for r in results if r is not None]
    dropped = len(results) - len(survivors)
    if dropped:
        logger.warning("%d clip(s) dropped — see preceding per-clip warnings", dropped)
    return survivors
