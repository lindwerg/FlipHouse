"""Pure-python virality aggregation (P2-S3).

The aggregate is computed here, never by the model: a weighted mean of the
assessed sub-scores (HOOK & PAYOFF ×2) times a deterministic length factor. The
non-integer weighted mean is the dispersion engine that substitutes for the
logprob smoothing OpenRouter→Gemini cannot expose.

No imports from llm/ and no network — small, exact, fully testable.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence

# HOOK and PAYOFF carry double weight (retention funnel: a clip lives or dies on
# the first line and on whether it pays off).
WEIGHTS: dict[str, int] = {
    "hook": 2,
    "payoff": 2,
    "emotion": 1,
    "visual": 1,
    "audio": 1,
    "pacing": 1,
}
SCORE_DIMS: tuple[str, ...] = ("hook", "emotion", "payoff", "visual", "audio", "pacing")
DIM_MODALITY: dict[str, str] = {
    "hook": "text",
    "emotion": "text",
    "payoff": "text",
    "pacing": "text",
    "visual": "video",
    "audio": "audio",
}
ALLOWED_MODALITIES: frozenset[str] = frozenset({"text", "video", "audio"})

# Length sweet-spot curve: full credit 21-34s, soft ramps to 15s / 45s, hard
# floor 0.60 beyond 8s / 75s (a long-but-strong clip is dampened, never zeroed).
_PEAK_LO, _PEAK_HI = 21.0, 34.0
_SOFT_LO, _SOFT_HI = 15.0, 45.0
_HARD_LO, _HARD_HI = 8.0, 75.0
_FLOOR = 0.60


def _lerp(a: float, b: float, t: float) -> float:
    return a + (b - a) * t


def length_factor(duration_s: float | None) -> float:
    """Deterministic length multiplier in [0.60, 1.0]; 1.0 when duration unknown."""
    if duration_s is None:
        return 1.0
    d = duration_s
    if _PEAK_LO <= d <= _PEAK_HI:
        return 1.0
    if _SOFT_LO <= d < _PEAK_LO:
        return _lerp(0.85, 1.0, (d - _SOFT_LO) / (_PEAK_LO - _SOFT_LO))
    if _PEAK_HI < d <= _SOFT_HI:
        return _lerp(1.0, 0.85, (d - _PEAK_HI) / (_SOFT_HI - _PEAK_HI))
    if _HARD_LO <= d < _SOFT_LO:
        return _lerp(0.60, 0.85, (d - _HARD_LO) / (_SOFT_LO - _HARD_LO))
    if _SOFT_HI < d <= _HARD_HI:
        return _lerp(0.85, 0.60, (d - _SOFT_HI) / (_HARD_HI - _SOFT_HI))
    return _FLOOR


def _validate(sub_scores: Mapping[str, object], modalities_used: object) -> None:
    """Fail-closed: raise ValueError on any malformed field (caller retries, never defaults)."""
    for dim in SCORE_DIMS:
        if dim not in sub_scores:
            raise ValueError(f"missing sub-score {dim!r}")
        value = sub_scores[dim]
        # bool is an int subclass and strict json_schema can return a float for an
        # "integer" field through some providers — reject both explicitly.
        if isinstance(value, bool) or not isinstance(value, int):
            raise ValueError(f"sub-score {dim!r} must be an int, got {type(value).__name__}")
        if not -1 <= value <= 100:
            raise ValueError(f"sub-score {dim!r} out of range [-1,100]: {value}")
    if not isinstance(modalities_used, list):
        raise ValueError("modalities_used must be a list")
    for modality in modalities_used:
        if modality not in ALLOWED_MODALITIES:
            raise ValueError(f"unknown modality {modality!r}")


def _is_assessed(
    dim: str, sub_scores: Mapping[str, object], modalities_used: Sequence[str]
) -> bool:
    """Dual gate: a dim counts iff its value is a real 0-100 score AND its modality was used."""
    value = sub_scores[dim]
    return 0 <= value <= 100 and DIM_MODALITY[dim] in modalities_used  # type: ignore[operator]


def aggregate_score(
    sub_scores: Mapping[str, object],
    modalities_used: object,
    duration_s: float | None = None,
) -> float:
    """Weighted mean of assessed sub-scores × length factor → one 0-100 float."""
    _validate(sub_scores, modalities_used)
    assessed = [d for d in SCORE_DIMS if _is_assessed(d, sub_scores, modalities_used)]  # type: ignore[arg-type]
    weight_sum = sum(WEIGHTS[d] for d in assessed)
    if weight_sum == 0:
        raise ValueError("no assessable sub-scores")
    base = sum(WEIGHTS[d] * sub_scores[d] for d in assessed) / weight_sum  # type: ignore[operator]
    # base ∈ [0,100] (weighted mean of in-range ints), length_factor ∈ [0.60,1.0]
    # → product ∈ [0,100]; no clamp needed.
    return round(base * length_factor(duration_s), 4)
