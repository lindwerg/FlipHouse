"""RANK-4 / EVAL-1: the eval-harness must validate the SELECTION threshold, not only
ranking — on a real-shaped score distribution, asserting the cut BINDS and the
duration floor does not silently govern.
"""

from __future__ import annotations

import random

import pytest

from fliphouse_worker.scoring import evaluate_threshold_binding
from fliphouse_worker.scoring.threshold_calibration import percentile_threshold

# A recorded-shape distribution of NORMALIZED rank values for a 2h run that recalls
# ~64 candidates: a realistic spread (most clips middling, a viral tail). Synthetic
# but representative — the founder's real labels graduate this later. Generated once
# with a fixed seed so the gate is deterministic.
_RNG = random.Random(20260625)
RECORDED_RANK_VALUES = tuple(
    round(_RNG.gauss(0.0, 1.0), 4) for _ in range(64)
)  # ~N(0,1): the per-model z-scores the cascade sorts on


def test_percentile_cut_binds_on_a_recorded_distribution():
    # With the default p75 cut the kept count lands in the founder's target band on
    # a realistic 64-candidate run — the threshold is doing real work, not collapsing
    # to ~1 the way the live absolute-55 cut did.
    report = evaluate_threshold_binding(
        RECORDED_RANK_VALUES, 75.0, min_keep=12, max_keep=25, floor=20
    )
    assert report.passed is True
    assert 12 <= report.kept <= 25


def test_eval_catches_the_floor_bypass_failure():
    # The exact live-run failure: a cut so high almost nothing clears it (top ~2%),
    # so only ~1 clip is kept and the duration floor fully governs — zero quality
    # content. The gate FAILS min_keep and flags floor_governs, surfacing the bypass.
    report = evaluate_threshold_binding(
        RECORDED_RANK_VALUES, 98.0, min_keep=12, max_keep=25, floor=20
    )
    assert report.kept < 12  # far below the band — the floor would govern
    assert report.floor_governs is True
    assert report.passed is False


def test_eval_catches_over_selection():
    # A cut so low almost everything passes (p5) → above the max band → FAIL.
    report = evaluate_threshold_binding(
        RECORDED_RANK_VALUES, 5.0, min_keep=12, max_keep=25, floor=20
    )
    assert report.kept > 25
    assert report.passed is False


def test_threshold_matches_percentile_helper():
    report = evaluate_threshold_binding(
        RECORDED_RANK_VALUES, 75.0, min_keep=0, max_keep=64, floor=0
    )
    assert report.threshold == percentile_threshold(RECORDED_RANK_VALUES, 75.0)
    assert report.n == 64


def test_empty_distribution_raises():
    with pytest.raises(ValueError):
        evaluate_threshold_binding([], 75.0, min_keep=1, max_keep=5, floor=1)
