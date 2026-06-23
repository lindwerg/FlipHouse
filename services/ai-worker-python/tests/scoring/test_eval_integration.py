"""Eval-harness integration for the scorer (P2-S3).

run_eval wires a text→score callable over the labeled clips and gates on the
eval-harness (Spearman vs human ranks AND score dispersion). Driven here by
deterministic mock scorers — no model call.
"""

from fliphouse_worker.eval import SEED_CLIPS
from fliphouse_worker.scoring import (
    RATIFIED_MIN_DISPERSION,
    RATIFIED_MIN_DIVERGENCE,
    RATIFIED_MIN_SPEARMAN,
    run_eval,
)
from fliphouse_worker.scoring.eval_runner import (
    DEFAULT_MIN_DISPERSION,
    DEFAULT_MIN_DIVERGENCE,
    DEFAULT_MIN_SPEARMAN,
)

_HUMAN_BY_TEXT = {c.text: c.human_score for c in SEED_CLIPS}


def test_eval_runner_passes_with_faithful_mock_scorer():
    report = run_eval(lambda text: float(_HUMAN_BY_TEXT[text]))
    assert report.passed
    assert report.spearman >= report.min_spearman
    assert report.dispersion >= report.min_dispersion


def test_eval_runner_fails_dispersion_with_clustered_mock():
    report = run_eval(lambda _text: 78.0)
    assert not report.passed
    assert report.dispersion < report.min_dispersion


def test_eval_runner_fails_spearman_with_inverted_mock():
    report = run_eval(lambda text: float(100 - _HUMAN_BY_TEXT[text]))
    assert not report.passed
    assert report.spearman < report.min_spearman


def test_ratified_floors_are_locked_constants():
    # The eval gate's bar is fixed (ratified), not a per-call knob.
    assert RATIFIED_MIN_SPEARMAN == 0.7
    assert RATIFIED_MIN_DISPERSION == 15.0
    assert RATIFIED_MIN_DIVERGENCE == 0.20
    # Back-compat aliases point at the ratified values.
    assert DEFAULT_MIN_SPEARMAN == RATIFIED_MIN_SPEARMAN
    assert DEFAULT_MIN_DISPERSION == RATIFIED_MIN_DISPERSION
    assert DEFAULT_MIN_DIVERGENCE == RATIFIED_MIN_DIVERGENCE


def test_eval_runner_inert_divergence_without_sub_scores():
    report = run_eval(lambda text: float(_HUMAN_BY_TEXT[text]))
    assert report.divergence is None
    assert report.min_divergence == RATIFIED_MIN_DIVERGENCE


def test_eval_runner_passes_divergence_with_discriminating_sub_scores():
    # Faithful aggregate ranking AND sub-scores that are not lockstep → all gates pass.
    def sub_scores_fn(text: str):
        base = _HUMAN_BY_TEXT[text]
        # payoff intentionally de-correlated from hook so divergence clears the floor.
        return {"hook": base, "payoff": (base * 7 + 23) % 100}

    report = run_eval(
        lambda text: float(_HUMAN_BY_TEXT[text]),
        sub_scores_fn=sub_scores_fn,
    )
    assert report.divergence is not None and report.divergence >= report.min_divergence
    assert report.passed


def test_eval_runner_fails_divergence_with_lockstep_sub_scores():
    # Good ranking + spread, but every sub-score equals the aggregate → lockstep.
    def sub_scores_fn(text: str):
        base = _HUMAN_BY_TEXT[text]
        return {"hook": base, "payoff": base}

    report = run_eval(
        lambda text: float(_HUMAN_BY_TEXT[text]),
        sub_scores_fn=sub_scores_fn,
    )
    assert report.divergence == 0.0
    assert not report.passed
