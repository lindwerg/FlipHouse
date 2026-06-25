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
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from enum import StrEnum
from typing import TypeVar

from ..clipping import CLIP_VIDEO_MIME, SAFE_FINALIST_PRESET, cut_clip
from ..concurrency import MapFn, ordered_threadpool_map
from ..scoring import ClipScorer, ScoredClip
from ..scoring.tiers import IDEAL, AvScope, TierConfig
from .recall import CandidateClip

logger = logging.getLogger(__name__)

MAX_SCORE_WORKERS = 6  # default cap on concurrent calls to one provider; tier overrides

# A/V-bearing modalities: a clip "got video" iff the model reported assessing at
# least one of these (text alone means the video was effectively dropped).
_AV_MODALITIES = frozenset({"video", "audio"})

T = TypeVar("T")
R = TypeVar("R")
CutFn = Callable[[str, float, float], bytes]

# The finalist A/V path uses the SAFE preset so a busy/long clip compresses under
# the OpenRouter inline cap WITHOUT -fs truncation (the truncation that otherwise
# corrupts the container and forces the silent text fallback ASK #7 is fixing).
finalist_cut = functools.partial(cut_clip, preset=SAFE_FINALIST_PRESET)


class DegradationReason(StrEnum):
    """Why a clip ended up text-only (or not) — the founder-visible A/V signal.

    Distinguishes the THREE silent text degradations the old code lumped together
    (all just ``used_video=False``): an intentional budget skip, a REAL A/V failure
    that fell back, and a clip scored WITH video whose modalities were dropped.
    """

    WANT_NONE = "want_none"  # budget / non-finalist: video never attempted (intentional)
    AV_OK = "av_ok"  # scored with video AND the model assessed video/audio
    AV_FAILED_TEXT = "av_failed_text"  # video attempted but cut/score failed → text fallback
    MODALITY_DROPPED = "modality_dropped"  # scored with video but model reported text-only


@dataclass(frozen=True)
class DegradationCounts:
    """How many finalist clips actually received video vs silently fell back to text."""

    av_succeeded: int = 0
    av_failed_fellback: int = 0
    modalities_dropped: int = 0
    budget_skipped: int = 0


@dataclass(frozen=True)
class ClipScore:
    """A candidate's Stage B result, whether it was scored with video, and why."""

    candidate: CandidateClip
    scored: ScoredClip
    used_video: bool
    reason: DegradationReason = DegradationReason.WANT_NONE


def count_degradations(scores: Iterable[ClipScore]) -> DegradationCounts:
    """Fold a batch of ClipScores into the visible A/V-vs-text degradation tally."""
    av_ok = av_failed = dropped = budget = 0
    for cs in scores:
        if cs.reason is DegradationReason.AV_OK:
            av_ok += 1
        elif cs.reason is DegradationReason.AV_FAILED_TEXT:
            av_failed += 1
        elif cs.reason is DegradationReason.MODALITY_DROPPED:
            dropped += 1
        else:  # WANT_NONE — intentional budget / non-finalist skip
            budget += 1
    return DegradationCounts(
        av_succeeded=av_ok,
        av_failed_fellback=av_failed,
        modalities_dropped=dropped,
        budget_skipped=budget,
    )


def _threadpool_map(
    fn: Callable[[T], R], items: Sequence[T], max_workers: int = MAX_SCORE_WORKERS
) -> list[R | None]:
    """Scoring's drop-and-continue fan-out — the shared util at this cap (back-compat alias)."""
    return ordered_threadpool_map(fn, items, max_workers=max_workers)


def _want_video_flags(tier: TierConfig, candidates: Sequence[CandidateClip]) -> list[bool]:
    """Per-candidate A/V flag from the tier's scope, POSITIONALLY aligned to ``candidates``.

    FINALISTS picks the top ``av_finalists_n`` by the free Stage-A ``dsp_prior`` (NOT
    input order — the segmenter now emits candidates in TIMELINE order, so the first
    N chronological windows are not the highest-potential ones). The returned flags
    stay positional so the caller's ``zip(candidates, flags)`` stays correct.
    """
    n = len(candidates)
    if tier.av_scope is AvScope.NONE:
        return [False] * n
    if tier.av_scope is AvScope.ALL:
        return [True] * n
    ranked = sorted(range(n), key=lambda i: candidates[i].dsp_prior, reverse=True)
    winners = set(ranked[: tier.av_finalists_n])  # top-N by free DSP prior
    logger.info(
        "A/V finalists: %d of %d candidates get video (av_finalists_n=%d)",
        len(winners),
        n,
        tier.av_finalists_n,
    )
    return [i in winners for i in range(n)]


def _score_one(
    cand: CandidateClip, scorer: ClipScorer, src: str, cut_fn: CutFn, want_video: bool = True
) -> ClipScore | None:
    """Cut + A/V score one candidate; fall back to text, then drop. Never raises.

    ``want_video=False`` (Бюджет / non-finalist) skips the A/V attempt entirely and
    scores text-only, reusing the same fail-closed text path.
    """
    duration = cand.end_time - cand.start_time
    text_reason = DegradationReason.WANT_NONE  # budget/non-finalist unless an A/V attempt failed
    if want_video:
        try:
            video = cut_fn(src, cand.start_time, cand.end_time)
            scored = scorer.score_clip(
                cand.text_excerpt, duration_s=duration, video=video, video_mime=CLIP_VIDEO_MIME
            )
            # The model may attach a clip yet report it assessed text only — a SILENT
            # degradation (#3): aggregate.py's dual gate counts it as text. Surface it.
            got_av = _AV_MODALITIES.intersection(scored.modalities_used)
            if not got_av:
                logger.warning(
                    "A/V clip [%s, %s] scored but model reported no video/audio modality "
                    "(modalities_used=%s); counting as text-only",
                    cand.start_time,
                    cand.end_time,
                    scored.modalities_used,
                )
                reason = DegradationReason.MODALITY_DROPPED
            else:
                reason = DegradationReason.AV_OK
            return ClipScore(candidate=cand, scored=scored, used_video=True, reason=reason)
        except Exception:
            logger.warning(
                "A/V scoring failed for clip [%s, %s]; falling back to text-only",
                cand.start_time,
                cand.end_time,
                exc_info=True,
            )
            text_reason = DegradationReason.AV_FAILED_TEXT  # a REAL failure, not a budget skip
    try:
        scored = scorer.score_clip(cand.text_excerpt, duration_s=duration)
        return ClipScore(candidate=cand, scored=scored, used_video=False, reason=text_reason)
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
    cut_fn: CutFn = finalist_cut,
    _map_fn: MapFn = _threadpool_map,
    tier: TierConfig = IDEAL,
) -> list[ClipScore]:
    """Score every candidate per the tier's A/V scope (fail-closed to text) → ClipScores."""
    flags = _want_video_flags(tier, candidates)
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
