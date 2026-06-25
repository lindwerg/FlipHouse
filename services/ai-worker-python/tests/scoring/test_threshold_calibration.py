"""RANK-2 / EVAL-1 coverage: threshold calibration replaces the magic 55."""

from __future__ import annotations

import pytest

from fliphouse_worker.scoring.threshold_calibration import (
    DEFAULT_TARGET_PERCENTILE,
    _percentile,
    calibrate_offsets,
    calibrate_threshold,
    percentile_threshold,
    resolve_target_percentile,
)


def test_internal_percentile_raises_on_empty():
    with pytest.raises(ValueError):
        _percentile([], 50.0)


# ── percentile_threshold (the shippable interim default) ────────────────────
def test_percentile_keeps_the_top_fraction():
    scores = [float(i) for i in range(100)]  # 0..99
    cut = percentile_threshold(scores, 75.0)
    kept = [s for s in scores if s >= cut]
    assert 24 <= len(kept) <= 26  # ~top quarter


def test_percentile_empty_passes_everything():
    assert percentile_threshold([], 90.0) == float("-inf")


def test_percentile_single_value():
    assert percentile_threshold([42.0], 90.0) == 42.0


def test_percentile_adapts_to_a_stingy_distribution():
    # A low-variance/low run: the cut is RELATIVE, so a sane fraction still passes
    # (unlike a fixed absolute 55 that would drop everything here).
    scores = [10.0, 11.0, 12.0, 13.0, 50.0]
    cut = percentile_threshold(scores, 75.0)
    assert any(s >= cut for s in scores)


def test_resolve_target_percentile_env(monkeypatch):
    monkeypatch.delenv("CLIP_TARGET_PERCENTILE", raising=False)
    assert resolve_target_percentile() == DEFAULT_TARGET_PERCENTILE
    monkeypatch.setenv("CLIP_TARGET_PERCENTILE", "90")
    assert resolve_target_percentile() == 90.0
    monkeypatch.setenv("CLIP_TARGET_PERCENTILE", "junk")
    assert resolve_target_percentile() == DEFAULT_TARGET_PERCENTILE
    monkeypatch.setenv("CLIP_TARGET_PERCENTILE", "150")  # out of range → default
    assert resolve_target_percentile() == DEFAULT_TARGET_PERCENTILE


# ── calibrate_threshold (labeled-set graduation path) ───────────────────────
def test_calibrate_recovers_a_bimodal_separating_cut():
    # Clearly separable: 👎 cluster ~10-20, 👍 cluster ~80-90. The F1-max cut sits
    # between the clusters, so it keeps every 👍 and no 👎.
    scores = [10.0, 15.0, 20.0, 80.0, 85.0, 90.0]
    labels = [False, False, False, True, True, True]
    fit = calibrate_threshold(scores, labels)
    assert 20.0 < fit.threshold <= 80.0
    assert fit.precision == 1.0
    assert fit.recall == 1.0
    assert fit.f1 == 1.0


def test_calibrate_precision_target_takes_highest_recall_clearing_it():
    scores = [10.0, 50.0, 55.0, 90.0]
    labels = [False, True, False, True]  # overlap in the middle
    fit = calibrate_threshold(scores, labels, min_precision=1.0)
    # only a cut above 55 yields precision 1.0 (keeps just the 90)
    assert fit.precision == 1.0
    assert fit.threshold > 55.0


def test_calibrate_rejects_single_class_labels():
    with pytest.raises(ValueError):
        calibrate_threshold([1.0, 2.0], [True, True])


def test_calibrate_rejects_length_mismatch_and_empty():
    with pytest.raises(ValueError):
        calibrate_threshold([1.0], [True, False])
    with pytest.raises(ValueError):
        calibrate_threshold([], [])


def test_calibrate_precision_target_unmet_falls_back_to_f1():
    # No cut reaches precision 1.0 here (a 👎 ties the top 👍), so it falls back to
    # the max-F1 cut rather than failing.
    scores = [10.0, 90.0, 90.0]
    labels = [False, True, False]
    fit = calibrate_threshold(scores, labels, min_precision=1.0)
    assert 0.0 <= fit.f1 <= 1.0


# ── calibrate_offsets (RANK-1 baselines from a labeled run) ─────────────────
def test_calibrate_offsets_are_per_model_means():
    offsets = calibrate_offsets({"lite": [80.0, 90.0], "flash": [50.0, 60.0]})
    assert offsets["lite"] == 85.0
    assert offsets["flash"] == 55.0


def test_calibrate_offsets_empty():
    assert calibrate_offsets({}) == {}
    assert calibrate_offsets({"lite": []}) == {}
