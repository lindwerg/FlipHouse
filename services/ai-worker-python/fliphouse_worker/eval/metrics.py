"""Pure-python metrics for the virality eval-harness (P2-S1).

No scipy/numpy in the production package — these are small, exact, and testable.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .dataset import LabeledClip


def _average_ranks(values: Sequence[float]) -> list[float]:
    """Rank values ascending; tied values share their averaged rank."""
    order = sorted(range(len(values)), key=lambda i: values[i])
    ranks = [0.0] * len(values)
    i = 0
    while i < len(order):
        j = i
        while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
            j += 1
        avg = (i + j) / 2 + 1  # 1-based average rank for the tie group
        for k in range(i, j + 1):
            ranks[order[k]] = avg
        i = j + 1
    return ranks


def _pearson(x: Sequence[float], y: Sequence[float]) -> float:
    n = len(x)
    mx = sum(x) / n
    my = sum(y) / n
    cov = sum((a - mx) * (b - my) for a, b in zip(x, y, strict=True))
    vx = sum((a - mx) ** 2 for a in x)
    vy = sum((b - my) ** 2 for b in y)
    if vx == 0 or vy == 0:
        return 0.0
    return cov / math.sqrt(vx * vy)


def spearman_rank_correlation(a: Sequence[float], b: Sequence[float]) -> float:
    """Spearman rank correlation (Pearson on average ranks). 0.0 if a side is flat."""
    if len(a) != len(b):
        raise ValueError("both series must be the same length")
    if len(a) < 2:
        raise ValueError("need at least 2 points")
    return _pearson(_average_ranks(a), _average_ranks(b))


def score_dispersion(scores: Sequence[float]) -> float:
    """Population standard deviation — the anti-clustering signal."""
    if not scores:
        raise ValueError("scores must be non-empty")
    mean = sum(scores) / len(scores)
    return math.sqrt(sum((s - mean) ** 2 for s in scores) / len(scores))


def sub_score_divergence(sub_scores_by_dim: Mapping[str, Sequence[float]]) -> float:
    """How independent the rubric's sub-scores are, across clips, in [0, 1].

    The DoD criterion "sub-scores diverge": a healthy rubric assesses *distinct*
    dimensions (hook, payoff, emotion, …). If every sub-score moves in lockstep
    across the clip set, the model collapsed the rubric to one undifferentiated
    signal — the per-dimension weights are then meaningless and the aggregate is
    no richer than a single number. We measure this as ``1 - mean(|pearson|)``
    over every distinct pair of sub-score dimensions:

      * lockstep dimensions (|r|→1 for all pairs) → divergence → 0 (BAD).
      * independent dimensions (|r|→0) → divergence → 1 (GOOD).

    A dimension that is flat across all clips (zero variance) carries no signal,
    so its pairwise correlations are treated as 0 (maximally divergent) — matching
    ``_pearson``'s zero-variance convention. Needs ≥2 dimensions and ≥2 clips.
    """
    dims = list(sub_scores_by_dim)
    if len(dims) < 2:
        raise ValueError("need at least 2 sub-score dimensions")
    lengths = {len(sub_scores_by_dim[d]) for d in dims}
    if len(lengths) != 1:
        raise ValueError("every dimension must have the same number of clip scores")
    if lengths == {0} or lengths == {1}:
        raise ValueError("need at least 2 clips per dimension")

    abs_corrs: list[float] = []
    for i in range(len(dims)):
        for j in range(i + 1, len(dims)):
            r = _pearson(sub_scores_by_dim[dims[i]], sub_scores_by_dim[dims[j]])
            abs_corrs.append(abs(r))
    return 1.0 - sum(abs_corrs) / len(abs_corrs)


@dataclass(frozen=True)
class EvalReport:
    n: int
    spearman: float
    dispersion: float
    divergence: float | None
    min_spearman: float
    min_dispersion: float
    min_divergence: float
    passed: bool


def evaluate(
    predicted: Mapping[str, float],
    clips: Sequence[LabeledClip],
    *,
    min_spearman: float,
    min_dispersion: float,
    sub_scores: Mapping[str, Mapping[str, float]] | None = None,
    min_divergence: float = 0.0,
) -> EvalReport:
    """Score a model's predictions against human reference labels.

    Gate = ranking agrees with humans (Spearman ≥ floor) AND aggregate scores are
    spread out, not clustered (dispersion ≥ floor) AND — when per-clip
    ``sub_scores`` are supplied — the rubric's sub-scores actually discriminate
    (divergence ≥ floor) instead of collapsing into one lockstep signal.

    ``sub_scores`` maps ``clip_id → {dimension: value}``; every clip and every
    dimension must be present. When omitted (text-only callers that keep only the
    aggregate), the divergence gate is inert (``divergence=None``, always passes).
    """
    predicted_scores: list[float] = []
    human: list[float] = []
    for clip in clips:
        if clip.clip_id not in predicted:
            raise KeyError(f"missing predicted score for clip {clip.clip_id!r}")
        predicted_scores.append(predicted[clip.clip_id])
        human.append(clip.human_score)

    spearman = spearman_rank_correlation(predicted_scores, human)
    dispersion = score_dispersion(predicted_scores)

    divergence: float | None = None
    divergence_ok = True
    if sub_scores is not None:
        divergence = _divergence_for_clips(sub_scores, clips)
        divergence_ok = divergence >= min_divergence

    passed = spearman >= min_spearman and dispersion >= min_dispersion and divergence_ok
    return EvalReport(
        n=len(clips),
        spearman=spearman,
        dispersion=dispersion,
        divergence=divergence,
        min_spearman=min_spearman,
        min_dispersion=min_dispersion,
        min_divergence=min_divergence,
        passed=passed,
    )


def _divergence_for_clips(
    sub_scores: Mapping[str, Mapping[str, float]],
    clips: Sequence[LabeledClip],
) -> float:
    """Pivot ``clip_id → {dim: value}`` into ``dim → [value per clip]`` then score.

    Dimensions are taken from the first clip and required to be identical on every
    other clip, so a missing/extra dimension fails loud rather than silently
    skewing the metric.
    """
    by_clip: list[Mapping[str, float]] = []
    for clip in clips:
        if clip.clip_id not in sub_scores:
            raise KeyError(f"missing sub-scores for clip {clip.clip_id!r}")
        by_clip.append(sub_scores[clip.clip_id])
    dims = list(by_clip[0])
    columns: dict[str, list[float]] = {d: [] for d in dims}
    for row in by_clip:
        if set(row) != set(dims):
            raise ValueError("every clip must carry the same sub-score dimensions")
        for d in dims:
            columns[d].append(float(row[d]))
    return sub_score_divergence(columns)
