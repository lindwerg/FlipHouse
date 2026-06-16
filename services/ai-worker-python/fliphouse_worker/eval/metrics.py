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


@dataclass(frozen=True)
class EvalReport:
    n: int
    spearman: float
    dispersion: float
    min_spearman: float
    min_dispersion: float
    passed: bool


def evaluate(
    predicted: Mapping[str, float],
    clips: Sequence[LabeledClip],
    *,
    min_spearman: float,
    min_dispersion: float,
) -> EvalReport:
    """Score a model's predictions against human reference labels.

    Gate = ranking agrees with humans (Spearman ≥ floor) AND scores are spread
    out, not clustered (dispersion ≥ floor).
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
    passed = spearman >= min_spearman and dispersion >= min_dispersion
    return EvalReport(
        n=len(clips),
        spearman=spearman,
        dispersion=dispersion,
        min_spearman=min_spearman,
        min_dispersion=min_dispersion,
        passed=passed,
    )
