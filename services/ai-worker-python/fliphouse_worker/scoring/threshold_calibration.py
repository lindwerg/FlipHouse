"""Quality-threshold calibration (RANK-2 / EVAL-1): fit the cut to a real distribution.

``DEFAULT_QUALITY_THRESHOLD = 55`` is an uncalibrated guess. On a real 2h run only
1/20 clips cleared it, so the duration SAFETY FLOOR silently governed selection —
the threshold never bound and selection count collapsed to a pure-duration constant
with no quality content. Billing is per source-minute (more clips ≠ more revenue),
so a threshold that never binds means margin is set by a duration heuristic, not
quality — the founder's stated reason the threshold is mandatory.

This module gives the threshold a real MECHANISM instead of a magic number:

  * ``percentile_threshold`` — the shippable INTERIM default: keep the top P% of a
    run's OWN normalized-score distribution. P is tuned (``CLIP_TARGET_PERCENTILE``)
    so a long video yields the founder's target band WITHOUT the duration floor
    firing. Distribution-relative, so it adapts to a generous or stingy run instead
    of a fixed absolute cut.
  * ``calibrate_threshold`` — once a labeled 👍/👎 set exists, pick the cut that
    maximizes F1 (or hits a precision target) against the labels. This needs real
    labels the founder has not produced yet, so it is the GRADUATION path, not the
    default — it never fabricates labels.
  * ``calibrate_offsets`` — derive RANK-1's per-model BASELINE offsets (each model's
    typical score) from a labeled set so the tiny-group normalization is centred
    correctly. Same label gate.

All pure python, no numpy, fully testable. The percentile path is what the cascade
wires in by default; the labeled paths are exercised by the eval-harness when a set
is supplied.
"""

from __future__ import annotations

import os
from collections.abc import Sequence
from dataclasses import dataclass

# Interim default: keep roughly the top quarter of a run's score distribution. On a
# 2h run that recalls ~60-80 candidates this lands selection in the founder's
# ~15-25 band, removing the duration-floor crutch, while a short low-variance video
# still yields a sane handful (guarded by the existing hard floor/cap in cascade).
DEFAULT_TARGET_PERCENTILE = 75.0


def resolve_target_percentile() -> float:
    """``CLIP_TARGET_PERCENTILE`` env → percentile in [0,100], default 75; bad value → default."""
    raw = os.environ.get("CLIP_TARGET_PERCENTILE", "").strip()
    if not raw:
        return DEFAULT_TARGET_PERCENTILE
    try:
        value = float(raw)
    except ValueError:
        return DEFAULT_TARGET_PERCENTILE
    return value if 0.0 <= value <= 100.0 else DEFAULT_TARGET_PERCENTILE


def _percentile(sorted_values: Sequence[float], pct: float) -> float:
    """Linear-interpolated percentile of an already-ascending sequence."""
    if not sorted_values:
        raise ValueError("need at least one value")
    if len(sorted_values) == 1:
        return sorted_values[0]
    rank = (len(sorted_values) - 1) * (pct / 100.0)
    low = int(rank)
    high = min(low + 1, len(sorted_values) - 1)
    frac = rank - low
    return sorted_values[low] * (1.0 - frac) + sorted_values[high] * frac


def percentile_threshold(scores: Sequence[float], target_percentile: float) -> float:
    """The cut that keeps the TOP ``(100 - target_percentile)``% of ``scores``.

    e.g. ``target_percentile=75`` returns the 75th-percentile value, so clips at/above
    it are the top quarter. Empty input → ``-inf`` (everything passes; the caller's
    hard floor/cap is the guardrail). Distribution-relative by construction.
    """
    if not scores:
        return float("-inf")
    return _percentile(sorted(scores), target_percentile)


@dataclass(frozen=True)
class ThresholdFit:
    """A labeled-set threshold fit: the chosen cut and its precision/recall/F1."""

    threshold: float
    precision: float
    recall: float
    f1: float


def _prf(scores: Sequence[float], labels: Sequence[bool], cut: float) -> tuple[float, float, float]:
    """Precision, recall, F1 of the rule ``score >= cut`` against boolean labels."""
    tp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= cut and y)
    fp = sum(1 for s, y in zip(scores, labels, strict=True) if s >= cut and not y)
    fn = sum(1 for s, y in zip(scores, labels, strict=True) if s < cut and y)
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return precision, recall, f1


def calibrate_threshold(
    scores: Sequence[float],
    labels: Sequence[bool],
    *,
    min_precision: float | None = None,
) -> ThresholdFit:
    """Pick the score cut that best separates 👍 from 👎 on a LABELED set.

    Candidate cuts are the distinct scores plus the midpoints between adjacent ones
    (so the chosen cut sits cleanly between a kept and a dropped clip). Default
    objective is max F1; pass ``min_precision`` to instead take the
    highest-recall cut whose precision clears that bar (a founder precision target).
    Requires equal-length, non-empty, both-class inputs — fails loud, never guesses.
    """
    if len(scores) != len(labels):
        raise ValueError("scores and labels must be the same length")
    if not scores:
        raise ValueError("need at least one labeled clip")
    if not any(labels) or all(labels):
        raise ValueError("need both 👍 and 👎 labels to calibrate a cut")

    uniq = sorted(set(scores))
    candidates = list(uniq)
    candidates += [(a + b) / 2.0 for a, b in zip(uniq, uniq[1:], strict=False)]
    candidates.append(min(uniq) - 1.0)  # a cut below everything (keep all)

    best: ThresholdFit | None = None
    for cut in candidates:
        precision, recall, f1 = _prf(scores, labels, cut)
        if min_precision is not None:
            if precision < min_precision:
                continue
            key = (recall, precision)
            best_key = (best.recall, best.precision) if best else (-1.0, -1.0)
        else:
            key = (f1, recall)  # type: ignore[assignment]
            best_key = (best.f1, best.recall) if best else (-1.0, -1.0)  # type: ignore[assignment]
        if best is None or key > best_key:
            best = ThresholdFit(threshold=cut, precision=precision, recall=recall, f1=f1)
    if best is None:  # no cut met the precision target → fall back to max-F1
        return calibrate_threshold(scores, labels)
    return best


def calibrate_offsets(
    scores_by_model: dict[str, Sequence[float]],
) -> dict[str, float]:
    """RANK-1 per-model BASELINE offsets = each model's own mean score.

    The normalizer standardizes a tiny group as ``(raw - baseline) / spread``; the
    baseline IS the model's typical score, so a STRICTER model (lower mean) yields a
    HIGHER normalized value for the same raw score — exactly encoding "flash is
    stricter than lite". Derived from the per-model score lists of a labeled run;
    returns ``{}`` for an empty input (the normalizer then defaults to the reference
    mean — distribution-free). Never fabricates a number.
    """
    return {model: sum(vals) / len(vals) for model, vals in scores_by_model.items() if vals}
