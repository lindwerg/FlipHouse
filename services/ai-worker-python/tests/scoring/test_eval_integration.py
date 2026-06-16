"""Eval-harness integration for the scorer (P2-S3).

run_eval wires a text→score callable over the labeled clips and gates on the
eval-harness (Spearman vs human ranks AND score dispersion). Driven here by
deterministic mock scorers — no model call.
"""

from fliphouse_worker.eval import SEED_CLIPS
from fliphouse_worker.scoring import run_eval

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
