"""Tests for the virality eval-harness metrics (P2-S1).

The harness is the gate that makes "maximal virality" measurable: it compares a
scorer's ranking of clips against human reference ranks (Spearman), guards against
score-clustering (dispersion floor), and checks sub-scores actually discriminate.
Pure-python metrics — no scipy/numpy in the production package.
"""

import math

import pytest

from fliphouse_worker.eval import (
    EvalReport,
    evaluate,
    score_dispersion,
    spearman_rank_correlation,
)
from fliphouse_worker.eval.dataset import LabeledClip

# ── Spearman ───────────────────────────────────────────────────────────────


def test_spearman_identical_is_one():
    assert spearman_rank_correlation([1, 2, 3, 4], [10, 20, 30, 40]) == pytest.approx(1.0)


def test_spearman_reversed_is_minus_one():
    assert spearman_rank_correlation([1, 2, 3, 4], [40, 30, 20, 10]) == pytest.approx(-1.0)


def test_spearman_known_case():
    # Classic worked example: rho = 1 - 6*Σd² / (n(n²-1)).
    a = [1, 2, 3, 4, 5]
    b = [2, 1, 4, 3, 5]  # d = [-1,1,-1,1,0] → Σd²=4 → rho = 1 - 24/120 = 0.8
    assert spearman_rank_correlation(a, b) == pytest.approx(0.8)


def test_spearman_handles_ties_via_average_ranks():
    # Ties get averaged ranks; identical-with-tie still perfectly correlated.
    assert spearman_rank_correlation([1, 1, 2], [5, 5, 9]) == pytest.approx(1.0)


def test_spearman_rejects_length_mismatch():
    with pytest.raises(ValueError, match="same length"):
        spearman_rank_correlation([1, 2], [1, 2, 3])


def test_spearman_rejects_too_few_points():
    with pytest.raises(ValueError, match="at least 2"):
        spearman_rank_correlation([1], [1])


def test_spearman_zero_variance_returns_zero():
    # A flat predicted series has no ranking signal → correlation defined as 0.
    assert spearman_rank_correlation([5, 5, 5], [1, 2, 3]) == 0.0


# ── dispersion ─────────────────────────────────────────────────────────────


def test_dispersion_of_constant_is_zero():
    assert score_dispersion([50, 50, 50]) == 0.0


def test_dispersion_known_value():
    # population std of [10,20,30] = sqrt(200/3) ≈ 8.165
    assert score_dispersion([10, 20, 30]) == pytest.approx(math.sqrt(200 / 3))


def test_dispersion_rejects_empty():
    with pytest.raises(ValueError, match="non-empty"):
        score_dispersion([])


# ── evaluate ───────────────────────────────────────────────────────────────


def _clips() -> list[LabeledClip]:
    return [
        LabeledClip(clip_id="a", text="boring logistics talk", human_score=10),
        LabeledClip(clip_id="b", text="mild anecdote", human_score=40),
        LabeledClip(clip_id="c", text="surprising reveal", human_score=70),
        LabeledClip(clip_id="d", text="shocking confession", human_score=95),
    ]


def test_evaluate_passes_when_scorer_matches_humans():
    predicted = {"a": 15, "b": 45, "c": 65, "d": 90}  # same order as humans
    report = evaluate(predicted, _clips(), min_spearman=0.5, min_dispersion=5.0)
    assert isinstance(report, EvalReport)
    assert report.n == 4
    assert report.spearman == pytest.approx(1.0)
    assert report.passed is True


def test_evaluate_fails_on_reversed_ranking():
    predicted = {"a": 90, "b": 65, "c": 45, "d": 15}  # inverse of humans
    report = evaluate(predicted, _clips(), min_spearman=0.5, min_dispersion=5.0)
    assert report.spearman == pytest.approx(-1.0)
    assert report.passed is False


def test_evaluate_fails_on_clustered_scores():
    # Good correlation but everything jammed in a 2-point band → clustering.
    predicted = {"a": 70, "b": 71, "c": 72, "d": 73}
    report = evaluate(predicted, _clips(), min_spearman=0.5, min_dispersion=5.0)
    assert report.dispersion < 5.0
    assert report.passed is False


def test_evaluate_requires_score_for_every_clip():
    with pytest.raises(KeyError, match="missing predicted score"):
        evaluate({"a": 10}, _clips(), min_spearman=0.5, min_dispersion=5.0)
