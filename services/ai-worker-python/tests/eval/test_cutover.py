"""Unit coverage for eval/cutover.py — seeded paired-bootstrap promotion gate.

Bootstrap math is seeded (random.Random(0)), so CI values are reproducible; the
'significance' scenario uses a hand-found dataset whose point estimate clears the
margin/power guards yet whose bootstrap CI straddles 0 (pinned to Python 3.11).
"""

import math
import random

import pytest

from fliphouse_worker.eval.cutover import CutoverReport, _percentile, evaluate_cutover
from fliphouse_worker.eval.dataset import LabeledClip


def test_percentile_integer_rank_and_interpolation():
    # rank lands on an integer index → direct pick; otherwise linear interpolation.
    assert _percentile([0.0, 1.0, 2.0, 3.0, 4.0], 50) == 2.0  # rank 2.0 (integer branch)
    assert _percentile([0.0, 1.0, 2.0, 3.0, 4.0], 0) == 0.0  # rank 0.0 (integer branch)
    assert _percentile([0.0, 10.0], 25) == pytest.approx(2.5)  # rank 0.25 (interpolated)


def _clips(humans):
    return [LabeledClip(f"c{i}", f"t{i}", h) for i, h in enumerate(humans)]


def _pred(values):
    return {f"c{i}": v for i, v in enumerate(values)}


def _monotonic_12():
    humans = list(range(12))
    return _clips(humans), humans


def test_promoted_when_all_guards_pass():
    clips, humans = _monotonic_12()
    champion = _pred([11 - h for h in humans])  # anti-correlated (spearman -1)
    challenger = _pred(humans)  # perfectly correlated (spearman 1)
    report = evaluate_cutover(
        champion,
        challenger,
        clips,
        min_spearman=0.5,
        min_dispersion=1.0,
        min_delta_spearman=0.6,
        n_bootstrap=200,
        rng=random.Random(0),
    )
    assert isinstance(report, CutoverReport)
    assert report.promoted is True and report.reason == "promoted"
    assert report.delta_spearman == pytest.approx(2.0)


def test_insufficient_n_abstains():
    humans = list(range(5))
    clips = _clips(humans)
    report = evaluate_cutover(
        _pred([4 - h for h in humans]),
        _pred(humans),
        clips,
        min_spearman=0.0,
        min_dispersion=0.1,
        min_delta_spearman=0.3,
        min_n=12,
        n_bootstrap=50,
        rng=random.Random(0),
    )
    assert report.promoted is False and report.reason == "insufficient_n"


def test_no_signal_difference_when_maps_identical():
    clips, humans = _monotonic_12()
    same = _pred(humans)
    report = evaluate_cutover(
        same,
        dict(same),
        clips,
        min_spearman=0.0,
        min_dispersion=0.1,
        min_delta_spearman=0.3,
        n_bootstrap=50,
        rng=random.Random(0),
    )
    assert report.promoted is False and report.reason == "no_signal_difference"


def test_floor_when_challenger_fails_dispersion():
    clips, humans = _monotonic_12()
    champion = _pred(humans)
    challenger = _pred([50.0] * 12)  # flat → dispersion 0, fails the floor
    report = evaluate_cutover(
        champion,
        challenger,
        clips,
        min_spearman=0.0,
        min_dispersion=1.0,
        min_delta_spearman=0.1,
        n_bootstrap=50,
        rng=random.Random(0),
    )
    assert report.promoted is False and report.reason == "floor"


def test_margin_when_no_improvement():
    clips, humans = _monotonic_12()
    champion = _pred([h * 2 for h in humans])  # different values, same ranking (sp 1)
    challenger = _pred(humans)  # also sp 1 → delta 0
    report = evaluate_cutover(
        champion,
        challenger,
        clips,
        min_spearman=0.0,
        min_dispersion=1.0,
        min_delta_spearman=0.6,
        n_bootstrap=50,
        rng=random.Random(0),
    )
    assert report.promoted is False and report.reason == "margin"


def test_underpowered_when_margin_below_mde():
    clips, humans = _monotonic_12()
    champion = _pred([11 - h for h in humans])
    challenger = _pred(humans)
    report = evaluate_cutover(
        champion,
        challenger,
        clips,
        min_spearman=0.0,
        min_dispersion=1.0,
        min_delta_spearman=0.3,  # < mde ≈ 0.566
        n_bootstrap=50,
        rng=random.Random(0),
    )
    assert report.min_delta_spearman < report.mde_estimate
    assert report.promoted is False and report.reason == "underpowered"


def test_significance_when_ci_includes_zero():
    # n=15 scenario (pinned): point estimate beats the margin and clears power,
    # but the bootstrap CI for ΔSpearman straddles 0 → not significant.
    champ = [
        14.1701,
        23.7929,
        3.6373,
        3.9193,
        -4.5172,
        44.7454,
        -10.8508,
        -21.1392,
        -11.1137,
        -10.165,
        -3.8106,
        -7.5671,
        -19.3885,
        -0.96,
        -1.1148,
    ]
    chall = [
        4.1544,
        -16.9021,
        -23.7527,
        -14.8469,
        6.5466,
        -1.6863,
        20.0082,
        25.1836,
        2.8663,
        -15.0385,
        23.6797,
        26.3398,
        5.7638,
        22.4974,
        1.943,
    ]
    clips = _clips(list(range(15)))
    mde = 1.96 / math.sqrt(15)
    report = evaluate_cutover(
        _pred(champ),
        _pred(chall),
        clips,
        min_spearman=0.0,
        min_dispersion=0.1,
        min_delta_spearman=round(mde, 4),
        min_n=4,
        n_bootstrap=150,  # default rng → internal Random(0)
    )
    assert report.delta_spearman >= report.min_delta_spearman
    assert report.min_delta_spearman >= report.mde_estimate
    assert report.delta_ci_low <= 0 < report.delta_ci_high
    assert report.promoted is False and report.reason == "significance"


def test_seeded_ci_is_reproducible():
    clips, humans = _monotonic_12()
    champion = _pred([11 - h for h in humans])
    challenger = _pred(humans)
    kw = dict(min_spearman=0.5, min_dispersion=1.0, min_delta_spearman=0.6, n_bootstrap=200)
    a = evaluate_cutover(champion, challenger, clips, rng=random.Random(0), **kw)
    b = evaluate_cutover(champion, challenger, clips, rng=random.Random(0), **kw)
    assert a.delta_ci_low == pytest.approx(b.delta_ci_low)
    assert a.delta_ci_high == pytest.approx(b.delta_ci_high)


def test_default_rng_is_deterministic_and_structural():
    clips, humans = _monotonic_12()
    champion = _pred([11 - h for h in humans])
    challenger = _pred(humans)
    kw = dict(min_spearman=0.5, min_dispersion=1.0, min_delta_spearman=0.6, n_bootstrap=100)
    # rng=None → resolves to Random(0) internally → reproducible across calls.
    a = evaluate_cutover(champion, challenger, clips, **kw)
    b = evaluate_cutover(champion, challenger, clips, **kw)
    assert isinstance(a.promoted, bool)
    assert a.delta_ci_low == pytest.approx(b.delta_ci_low)
