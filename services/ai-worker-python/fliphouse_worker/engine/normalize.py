"""Cross-model score normalization (RANK-1): make aggregates comparable before pooling.

Absolute LLM-judge scores are NOT comparable across models. The cascade scores
clips on THREE different routes — ``SCORING`` (gemini-3.1-flash-lite, the cheap
text path), ``SCORING_MULTIMODAL`` (gemini-3.5-flash, the A/V finalists), and the
``OFFER_MATCH`` escalation tier — then pools every aggregate into ONE list and
sorts on the raw number. A model that runs a few points more generous mechanically
outranks a stricter model's equally-or-more viral clip. That is exactly the
observed "text-lite outranks video-flash" failure: the A/V finalists the cascade
paid Vertex for can be buried below un-escalated text clips.

The fix is distribution-free: group clips by ``model_used`` and convert each clip's
aggregate to a per-model standardized score, then sort/threshold on THAT.

  * group of ≥ ``MIN_GROUP_FOR_Z`` members → z-score within the group (mean 0,
    unit std), so a clip's rank reflects how it stands AMONG ITS OWN MODEL'S
    distribution, not a cross-model absolute.
  * tiny group (< ``MIN_GROUP_FOR_Z``) — the A/V / escalation tiers are small
    (≤8) and have no usable spread of their own — is standardized against the
    LARGEST group's (mean, std) REFERENCE distribution (minus a calibrated
    per-model bias offset, default 0). Measuring a flash A/V clip against the text
    group's distribution is precisely what lets a stricter-model 65 outrank a
    generous-model 70: the 65 sits HIGH relative to the (lower-mean) reference it
    is placed against, while the 70 sits only mid relative to its own (higher-mean)
    distribution. The offsets default to 0 (distribution-free) and are tunable from
    RANK-2's calibration once a labeled set exists — shipping the reference z-score
    first keeps the default behaviour free of any fabricated calibration number.

PURE: no network, no mutation. Returns NEW per-clip normalized values keyed by the
INPUT INDEX, so the caller carries the raw aggregate for display/billing and only
sorts/thresholds on the normalized value.
"""

from __future__ import annotations

import math
import os
from collections.abc import Sequence
from typing import Protocol

# A group needs at least this many members for a within-group z-score to be
# meaningful (a 1-2 member group has no usable spread). Below it, standardize
# against the largest group's reference distribution.
MIN_GROUP_FOR_Z = 3
# Nominal aggregate spread (0-100 scale) used as a last-resort reference std when
# even the largest group is degenerate (flat / a single clip): (raw - ref_mean) /
# NOMINAL_STD still gives a sane monotonic placement.
NOMINAL_STD = 15.0
# A model whose entire group is a single flat value contributes zero spread; its
# z is 0 (the group mean), which is the correct distribution-free position.
_ZERO = 0.0


class _Scored(Protocol):
    aggregate: float
    model_used: str


class _HasScored(Protocol):
    @property
    def scored(self) -> _Scored: ...


def _calibrated_offsets() -> dict[str, float]:
    """Per-model BASELINE offsets (the model's typical score) for tiny-group standardizing.

    Default empty (no model has a recorded baseline → tiny groups fall back to the
    reference group's mean, distribution-free). RANK-2's ``calibrate_offsets`` emits
    the real per-model baselines once a labeled set exists; they are injected here
    via ``CLIP_MODEL_OFFSETS`` (JSON ``{"model": baseline}``) so the knob ships
    without fabricating calibration numbers.
    """
    raw = os.environ.get("CLIP_MODEL_OFFSETS", "").strip()
    if not raw:
        return {}
    import json

    try:
        parsed = json.loads(raw)
    except (ValueError, TypeError):
        return {}
    if not isinstance(parsed, dict):
        return {}
    return {str(k): float(v) for k, v in parsed.items() if _is_number(v)}


def _is_number(v: object) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _zscore(value: float, mean: float, std: float) -> float:
    """Standardize within a group; flat group (std≈0) → 0 (the group mean position)."""
    if std <= 1e-9:
        return _ZERO
    return (value - mean) / std


def _group_stats(values: Sequence[float]) -> tuple[float, float]:
    """(mean, population std) of a group's aggregates."""
    n = len(values)
    mean = sum(values) / n
    std = math.sqrt(sum((v - mean) ** 2 for v in values) / n)
    return mean, std


def normalized_rank_values(
    scores: Sequence[_HasScored],
    *,
    offsets: dict[str, float] | None = None,
) -> list[float]:
    """Per-clip normalized rank value, POSITIONALLY aligned to ``scores``.

    Groups by ``scored.model_used``; a ≥``MIN_GROUP_FOR_Z`` group is z-scored
    within itself. A tiny group (no usable spread of its own) is standardized as
    ``(raw - baseline) / spread`` where:

      * ``baseline`` is the model's OWN baseline = its calibrated offset when one is
        supplied (this is how "flash is stricter than lite" is encoded: a stricter
        model has a LOWER baseline, so the same raw score yields a HIGHER z), and
        falls back to the largest group's reference mean when no offset exists
        (distribution-free default — it cannot invent a strictness it was not told).
      * ``spread`` is the reference group's std (a nominal fallback if degenerate).

    This makes the tiny-group formula consistent with the big-group z-score, whose
    own ``(raw - group_mean)/group_std`` IS a (raw - baseline)/spread with the
    model's empirical baseline. When every clip shares ONE model the result is a
    pure within-model z-score — a monotonic transform of the raw aggregate, so the
    ranking is UNCHANGED (the property the single-model eval relies on).
    """
    resolved_offsets = offsets if offsets is not None else _calibrated_offsets()
    indices_by_model: dict[str, list[int]] = {}
    for i, cs in enumerate(scores):
        indices_by_model.setdefault(cs.scored.model_used, []).append(i)

    # Reference axis for tiny groups = the largest model group (the text tier
    # dominates count). Its (mean, std) is the default yardstick a single
    # A/V/escalation clip is measured against when no per-model offset is supplied.
    ref_mean, ref_std = _reference_stats(scores, indices_by_model)
    spread = ref_std if ref_std > 1e-9 else NOMINAL_STD

    out: list[float] = [0.0] * len(scores)
    for model, idxs in indices_by_model.items():
        aggregates = [scores[i].scored.aggregate for i in idxs]
        if len(idxs) >= MIN_GROUP_FOR_Z:
            mean, std = _group_stats(aggregates)
            for i in idxs:
                out[i] = _zscore(scores[i].scored.aggregate, mean, std)
        else:
            # A calibrated offset (the model's strictness/generosity baseline) takes
            # precedence; absent one, fall back to the reference mean — distribution
            # -free, never inventing a strictness the calibration did not record.
            baseline = resolved_offsets[model] if model in resolved_offsets else ref_mean
            for i in idxs:
                out[i] = (scores[i].scored.aggregate - baseline) / spread
    return out


def _reference_stats(
    scores: Sequence[_HasScored], indices_by_model: dict[str, list[int]]
) -> tuple[float, float]:
    """(mean, std) of the LARGEST model group — the default reference axis for tiny groups.

    Ties on size break toward the group with the most spread (the more informative
    reference). Empty input → (0, 0); the caller then falls back to NOMINAL_STD.
    """
    if not scores:
        return 0.0, 0.0
    best_idxs: list[int] = []
    best_key: tuple[int, float] = (-1, -1.0)
    for idxs in indices_by_model.values():
        _, std = _group_stats([scores[i].scored.aggregate for i in idxs])
        key = (len(idxs), std)
        if key > best_key:
            best_key, best_idxs = key, idxs
    return _group_stats([scores[i].scored.aggregate for i in best_idxs])
