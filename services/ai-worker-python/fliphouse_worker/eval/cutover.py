"""Cutover gate (P2-S7) — promote the new cascade over the baseline, or abstain.

The final P2 acceptance bar. Layered above ``metrics.evaluate``: it compares a
challenger's predictions (e.g. the native-A/V cascade) against a champion's (the
prior text-only path) on the same human-labeled set and promotes ONLY when every
guard holds — otherwise it fails closed and keeps the champion.

Guards, in precedence order (``reason`` names the first failure):
  insufficient_n      — dataset smaller than ``min_n`` → abstain.
  no_signal_difference — challenger predictions identical to champion → no signal.
  floor               — challenger fails the absolute Spearman/dispersion floors.
  margin              — challenger does not beat the champion by ``min_delta_spearman``.
  underpowered        — the required margin is below the dataset's MDE → abstain.
  significance        — the bootstrap CI for ΔSpearman includes 0 → not significant.

All bootstrap/percentile math is pure python (no numpy) and seeded for
determinism: ``rng`` defaults to ``random.Random(0)`` resolved INSIDE the function
so the no-arg path is reproducible and assertable.
"""

from __future__ import annotations

import math
import random
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .dataset import LabeledClip
from .metrics import EvalReport, evaluate, spearman_rank_correlation


@dataclass(frozen=True)
class CutoverReport:
    champion_report: EvalReport
    challenger_report: EvalReport
    delta_spearman: float
    delta_ci_low: float
    delta_ci_high: float
    min_delta_spearman: float
    mde_estimate: float
    n: int
    min_n: int
    promoted: bool
    reason: str


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-sorted sequence."""
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = math.floor(rank)
    high = math.ceil(rank)
    if low == high:
        return sorted_values[int(rank)]
    return sorted_values[low] * (high - rank) + sorted_values[high] * (rank - low)


def _bootstrap_delta_ci(
    champion: Sequence[float],
    challenger: Sequence[float],
    human: Sequence[float],
    *,
    n_bootstrap: int,
    rng: random.Random,
) -> tuple[float, float]:
    """Paired bootstrap CI for ΔSpearman (challenger − champion) on resampled clips."""
    n = len(human)
    deltas: list[float] = []
    for _ in range(n_bootstrap):
        idx = [rng.randrange(n) for _ in range(n)]
        h = [human[j] for j in idx]
        champ_delta = spearman_rank_correlation([challenger[j] for j in idx], h)
        base_delta = spearman_rank_correlation([champion[j] for j in idx], h)
        deltas.append(champ_delta - base_delta)
    deltas.sort()
    return _percentile(deltas, 2.5), _percentile(deltas, 97.5)


def _decide(
    *,
    n: int,
    min_n: int,
    maps_differ: bool,
    challenger_passed: bool,
    delta_spearman: float,
    min_delta_spearman: float,
    mde_estimate: float,
    ci_low: float,
) -> tuple[bool, str]:
    """First failing guard wins; all pass → promote."""
    if n < min_n:
        return False, "insufficient_n"
    if not maps_differ:
        return False, "no_signal_difference"
    if not challenger_passed:
        return False, "floor"
    if delta_spearman < min_delta_spearman:
        return False, "margin"
    if min_delta_spearman < mde_estimate:
        return False, "underpowered"
    if ci_low <= 0:
        return False, "significance"
    return True, "promoted"


def evaluate_cutover(
    champion_pred: Mapping[str, float],
    challenger_pred: Mapping[str, float],
    clips: Sequence[LabeledClip],
    *,
    min_spearman: float,
    min_dispersion: float,
    min_delta_spearman: float,
    min_n: int = 12,
    n_bootstrap: int = 2000,
    rng: random.Random | None = None,
) -> CutoverReport:
    """Decide whether the challenger may replace the champion. Fails closed."""
    resolved_rng = rng if rng is not None else random.Random(0)
    n = len(clips)
    champion_report = evaluate(
        champion_pred, clips, min_spearman=min_spearman, min_dispersion=min_dispersion
    )
    challenger_report = evaluate(
        challenger_pred, clips, min_spearman=min_spearman, min_dispersion=min_dispersion
    )
    delta_spearman = challenger_report.spearman - champion_report.spearman
    mde_estimate = 1.96 / math.sqrt(n)

    human = [clip.human_score for clip in clips]
    champion_scores = [champion_pred[clip.clip_id] for clip in clips]
    challenger_scores = [challenger_pred[clip.clip_id] for clip in clips]
    ci_low, ci_high = _bootstrap_delta_ci(
        champion_scores, challenger_scores, human, n_bootstrap=n_bootstrap, rng=resolved_rng
    )

    promoted, reason = _decide(
        n=n,
        min_n=min_n,
        maps_differ=champion_scores != challenger_scores,
        challenger_passed=challenger_report.passed,
        delta_spearman=delta_spearman,
        min_delta_spearman=min_delta_spearman,
        mde_estimate=mde_estimate,
        ci_low=ci_low,
    )
    return CutoverReport(
        champion_report=champion_report,
        challenger_report=challenger_report,
        delta_spearman=delta_spearman,
        delta_ci_low=ci_low,
        delta_ci_high=ci_high,
        min_delta_spearman=min_delta_spearman,
        mde_estimate=mde_estimate,
        n=n,
        min_n=min_n,
        promoted=promoted,
        reason=reason,
    )
