"""Opt-in live Gemini smoke + eval (P2-S3).

Skipped unless FLIPHOUSE_LIVE_GEMINI is set (CI never sets it), so it never runs
in the coverage gate. Founder runs it with his paid OPENROUTER_API_KEY to prove
the -1-sentinel / no-item-enum schema survives Gemini strict-mode via OpenRouter
AND that the full seed eval clears the floors (a calibration run — read the
printed dispersion before locking the floor).
"""

import os

import pytest

from fliphouse_worker.eval import SEED_CLIPS
from fliphouse_worker.llm import OpenRouterAdapter
from fliphouse_worker.scoring import ClipScorer, run_eval

pytestmark = pytest.mark.skipif(
    not os.getenv("FLIPHOUSE_LIVE_GEMINI"),
    reason="live test — set FLIPHOUSE_LIVE_GEMINI=1 and OPENROUTER_API_KEY",
)


@pytest.mark.live
def test_live_gemini_smoke_and_eval():  # pragma: no cover
    scorer = ClipScorer(OpenRouterAdapter())
    scored = scorer.score_clip("Я потерял миллион долларов за один день. И вот что я понял.")
    assert scored.modalities_used == ["text"]
    assert scored.sub_scores["visual"] == -1
    assert scored.sub_scores["audio"] == -1
    assert 0.0 <= scored.aggregate <= 100.0

    report = run_eval(lambda text: scorer.score_clip(text).aggregate, clips=SEED_CLIPS)
    print(f"LIVE EVAL: spearman={report.spearman:.3f} dispersion={report.dispersion:.2f}")
    assert report.passed
