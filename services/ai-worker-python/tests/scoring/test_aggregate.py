"""Pure-function tests for the virality aggregation (P2-S3).

The aggregate is computed in Python, never by the model: weighted mean of the
assessed sub-scores (HOOK & PAYOFF ×2) times a deterministic length factor.
"""

import pytest

from fliphouse_worker.scoring import aggregate_score, length_factor


def _text_only(**overrides) -> dict:
    base = {"hook": 50, "emotion": 50, "payoff": 50, "visual": -1, "audio": -1, "pacing": 50}
    base.update(overrides)
    return base


# ── length_factor ────────────────────────────────────────────────────────


def test_length_factor_none_is_one():
    assert length_factor(None) == 1.0


def test_length_factor_full_credit_plateau():
    assert length_factor(21) == 1.0
    assert length_factor(27) == 1.0
    assert length_factor(34) == 1.0


def test_length_factor_soft_edges():
    assert length_factor(15) == pytest.approx(0.85)
    assert length_factor(45) == pytest.approx(0.85)


def test_length_factor_hard_floor_endpoints():
    assert length_factor(8) == pytest.approx(0.60)
    assert length_factor(75) == pytest.approx(0.60)


def test_length_factor_below_and_above_hard_bounds_is_floor():
    assert length_factor(5) == 0.60
    assert length_factor(120) == 0.60


def test_length_factor_interpolation_segments():
    assert length_factor(18) == pytest.approx(0.925)  # mid 15->21 rising
    assert length_factor(11) == pytest.approx(0.60 + 0.25 * (3 / 7))  # 8->15 rising
    assert length_factor(60) == pytest.approx(0.725)  # 45->75 falling, halfway
    assert length_factor(39.5) == pytest.approx(0.925)  # 34->45 falling, halfway


# ── aggregate weighting ──────────────────────────────────────────────────


def test_aggregate_weights_hook_payoff_double():
    high = aggregate_score(_text_only(hook=100, payoff=100, emotion=0, pacing=0), ["text"])
    assert high == round(400 / 6, 4)  # (2*100 + 2*100 + 0 + 0) / 6, 4dp
    low = aggregate_score(_text_only(hook=0, payoff=0, emotion=100, pacing=100), ["text"])
    assert low == round(200 / 6, 4)  # (0 + 0 + 100 + 100) / 6, 4dp


def test_aggregate_excludes_visual_audio_via_sentinel_value():
    # visual/audio = -1 → dropped by the value gate; denominator stays 6.
    assert aggregate_score(_text_only(), ["text"]) == 50.0


def test_aggregate_excludes_visual_audio_when_zero_but_modality_absent():
    # must_fix: visual/audio = 0 (a real-looking score) but their modality is not
    # in modalities_used → excluded by the modality gate, NOT just the value gate.
    result = aggregate_score(
        {"hook": 80, "emotion": 80, "payoff": 80, "visual": 0, "audio": 0, "pacing": 80},
        ["text"],
    )
    assert result == 80.0  # denom 6, not 8


def test_aggregate_full_av_path_denominator_eight():
    # S6 zero-churn: same function, all six assessed → W=8.
    result = aggregate_score(
        {"hook": 60, "emotion": 60, "payoff": 60, "visual": 60, "audio": 60, "pacing": 60},
        ["text", "video", "audio"],
    )
    assert result == 60.0


def test_aggregate_applies_length_factor():
    assert aggregate_score(_text_only(), ["text"], duration_s=8) == 30.0  # 50 * 0.60
    assert aggregate_score(_text_only(), ["text"], duration_s=27) == 50.0  # 50 * 1.0
    assert aggregate_score(_text_only(), ["text"], duration_s=None) == 50.0


def test_aggregate_is_deterministic_and_float():
    a = aggregate_score(_text_only(hook=100, payoff=100, emotion=0, pacing=0), ["text"])
    b = aggregate_score(_text_only(hook=100, payoff=100, emotion=0, pacing=0), ["text"])
    assert a == b
    assert isinstance(a, float)


# ── fail-closed validation ───────────────────────────────────────────────


def test_aggregate_raises_on_missing_key():
    sub = _text_only()
    del sub["pacing"]
    with pytest.raises(ValueError, match="pacing"):
        aggregate_score(sub, ["text"])


def test_aggregate_rejects_float_str_none_and_bool():
    for bad in (50.0, "50", None, True):
        with pytest.raises(ValueError):
            aggregate_score(_text_only(hook=bad), ["text"])


def test_aggregate_raises_on_out_of_range_value():
    with pytest.raises(ValueError):
        aggregate_score(_text_only(hook=150), ["text"])


def test_aggregate_raises_on_modalities_not_a_list():
    with pytest.raises(ValueError):
        aggregate_score(_text_only(), 123)


def test_aggregate_raises_on_unknown_modality():
    with pytest.raises(ValueError, match="modal"):
        aggregate_score(_text_only(), ["text", "smell"])


def test_aggregate_raises_when_no_dimension_assessed():
    # every dim abstained → W == 0 → ValueError, never ZeroDivisionError.
    allna = {"hook": -1, "emotion": -1, "payoff": -1, "visual": -1, "audio": -1, "pacing": -1}
    with pytest.raises(ValueError):
        aggregate_score(allna, ["text"])
