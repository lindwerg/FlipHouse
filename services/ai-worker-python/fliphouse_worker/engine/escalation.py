"""Borderline-clip escalation (P2-S7).

After Stage B ranks the clips, the ones near the top-k cutoff (rank-margin) or
with low self-reported confidence are re-scored on a stronger route before the
final ranking. Cheap-first, escalate-on-uncertainty — the doc-04 §2.5 pattern.

Two pure-ish pieces, both injectable from the cascade:
  ``borderline_indices`` — a pure detector (no scorer, no network): which ranked
  indices are borderline, capped and deterministically tie-broken.
  ``escalate_borderline`` — re-scores the borderline clips fail-closed (a failed
  re-score keeps the ORIGINAL clip, never drops it), returning the new ranked
  list, the count that actually upgraded, and each escalation call's
  (model, usage) so the cost fold loses no paid call.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence

from ..clipping import CLIP_VIDEO_MIME
from ..llm import Profile
from ..scoring import ClipScorer, ScoredClip
from ..scoring.tiers import TierConfig
from .scoring_fanout import ClipScore, CutFn

logger = logging.getLogger(__name__)

RescoreFn = Callable[..., ScoredClip]
SelectFn = Callable[..., tuple[int, ...]]
EscalateFn = Callable[..., tuple[list[ClipScore], int, tuple[tuple[str, dict], ...]]]


def borderline_indices(
    ranked: Sequence[ClipScore],
    k: int,
    *,
    conf_floor: int,
    gap_eps: float,
    max_escalations: int,
) -> tuple[int, ...]:
    """Indices (into the aggregate-desc ``ranked``) worth escalating, capped.

    Borderline = aggregate within ``gap_eps`` of the top-k cutoff (rank-margin,
    PRIMARY) OR confidence < ``conf_floor`` (SECONDARY). There is a cutoff contest
    only when ``0 < k < len(ranked)``; otherwise only the confidence rule fires.
    Capped to ``max_escalations``, ordered by (distance-to-cutoff asc, index asc)
    for a stable, reproducible pick even with tied integer aggregates.
    """
    if max_escalations <= 0 or not ranked:
        return ()
    n = len(ranked)
    has_contest = 0 < k < n
    boundary = ranked[k - 1].scored.aggregate if has_contest else 0.0
    flagged: list[tuple[float, int]] = []
    for i, clip in enumerate(ranked):
        dist = abs(clip.scored.aggregate - boundary)
        primary = has_contest and dist < gap_eps
        secondary = clip.scored.confidence < conf_floor
        if primary or secondary:
            flagged.append((dist if has_contest else 0.0, i))
    flagged.sort(key=lambda t: (t[0], t[1]))
    return tuple(i for _, i in flagged[:max_escalations])


def _default_rescore(
    clip: ClipScore, scorer: ClipScorer, src: str, *, profile: Profile, cut_fn: CutFn
) -> ScoredClip:
    """Re-score one clip on the escalation route; re-cut only if it was A/V-scored."""
    duration = clip.candidate.end_time - clip.candidate.start_time
    if clip.used_video:
        video = cut_fn(src, clip.candidate.start_time, clip.candidate.end_time)
        return scorer.score_clip(
            clip.candidate.text_excerpt,
            duration_s=duration,
            video=video,
            video_mime=CLIP_VIDEO_MIME,
            profile_override=profile,
        )
    return scorer.score_clip(
        clip.candidate.text_excerpt, duration_s=duration, profile_override=profile
    )


def escalate_borderline(
    ranked: list[ClipScore],
    scorer: ClipScorer,
    src: str,
    *,
    k: int,
    tier: TierConfig,
    cut_fn: CutFn,
    _select_fn: SelectFn = borderline_indices,
    _rescore_fn: RescoreFn = _default_rescore,
) -> tuple[list[ClipScore], int, tuple[tuple[str, dict], ...]]:
    """Re-score borderline clips on ``tier.escalation_profile``; fail-closed, immutable."""
    if not tier.escalate or tier.escalation_max_clips <= 0 or tier.escalation_profile is None:
        return ranked, 0, ()
    indices = _select_fn(
        ranked,
        k,
        conf_floor=tier.escalation_confidence_floor,
        gap_eps=tier.escalation_gap_epsilon,
        max_escalations=tier.escalation_max_clips,
    )
    if not indices:
        return ranked, 0, ()

    profile = tier.escalation_profile
    new_ranked = list(ranked)
    usages: list[tuple[str, dict]] = []
    count = 0
    for i in indices:
        clip = ranked[i]
        try:
            rescored = _rescore_fn(clip, scorer, src, profile=profile, cut_fn=cut_fn)
        except Exception:
            logger.warning(
                "escalation re-score failed for clip [%s, %s]; keeping original",
                clip.candidate.start_time,
                clip.candidate.end_time,
                exc_info=True,
            )
            continue
        new_ranked[i] = ClipScore(
            candidate=clip.candidate, scored=rescored, used_video=clip.used_video
        )
        usages.append((rescored.model_used, rescored.raw_usage))
        count += 1
    return new_ranked, count, tuple(usages)
