"""Opt-in live Gemini smoke + eval (P2-S3).

Skipped unless FLIPHOUSE_LIVE_GEMINI is set (CI never sets it), so it never runs
in the coverage gate. Founder runs it with his paid OPENROUTER_API_KEY to prove
the -1-sentinel / no-item-enum schema survives Gemini strict-mode via OpenRouter
AND that the full seed eval clears the floors (a calibration run — read the
printed dispersion before locking the floor).
"""

import os
from pathlib import Path

import pytest

from fliphouse_worker.clipping import CLIP_VIDEO_MIME
from fliphouse_worker.eval import SEED_CLIPS, evaluate, evaluate_cutover, load_av_clips
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

    # Score once per clip, reuse for both the aggregate and the sub-score
    # divergence gate so the live run proves all three ratified floors at once.
    scored = {c.text: scorer.score_clip(c.text) for c in SEED_CLIPS}
    report = run_eval(
        lambda text: scored[text].aggregate,
        clips=SEED_CLIPS,
        sub_scores_fn=lambda text: {k: float(v) for k, v in scored[text].sub_scores.items()},
    )
    print(
        f"LIVE EVAL: spearman={report.spearman:.3f} dispersion={report.dispersion:.2f} "
        f"divergence={report.divergence}"
    )
    assert report.passed


@pytest.mark.live
def test_live_gemini_media_strict_json():  # pragma: no cover
    # Proves base64 video + strict json_schema coexist on the SCORING_MULTIMODAL
    # (Vertex-pinned) route. Point FLIPHOUSE_LIVE_CLIP at a small real .mp4.
    clip_path = os.getenv("FLIPHOUSE_LIVE_CLIP")
    if not clip_path:
        pytest.skip("set FLIPHOUSE_LIVE_CLIP to a small real .mp4 file")
    video = Path(clip_path).read_bytes()
    scorer = ClipScorer(OpenRouterAdapter())
    scored = scorer.score_clip("Watch this moment.", video=video)
    assert 0.0 <= scored.aggregate <= 100.0
    assert "video" in scored.modalities_used


@pytest.mark.live
def test_live_gemini_av_beats_text():  # pragma: no cover
    # Lane 2 (founder-run, never in CI/coverage): proves the native-A/V cascade
    # ranks clips at least as well as text-only on Spearman, on the PRODUCTION
    # webm path. Founder hand-cuts >=3 real webm clips + a manifest and points
    # FLIPHOUSE_AV_MANIFEST at it (plus FLIPHOUSE_LIVE_GEMINI + OPENROUTER_API_KEY).
    manifest = os.getenv("FLIPHOUSE_AV_MANIFEST")
    if not manifest or not Path(manifest).is_file():
        pytest.skip("set FLIPHOUSE_AV_MANIFEST to a JSON manifest of >=3 real webm clips")
    clips = load_av_clips(manifest)
    assert len(clips) >= 3, "A/V comparison needs >=3 clips to be meaningful"

    scorer = ClipScorer(OpenRouterAdapter())
    text_map = {
        c.clip_id: scorer.score_clip(c.text, duration_s=c.duration_s).aggregate for c in clips
    }
    av_map = {
        c.clip_id: scorer.score_clip(
            c.text,
            duration_s=c.duration_s,
            video=c.clip_path.read_bytes(),
            video_mime=CLIP_VIDEO_MIME,
        ).aggregate
        for c in clips
    }
    text_report = evaluate(text_map, clips, min_spearman=0.0, min_dispersion=0.0)
    av_report = evaluate(av_map, clips, min_spearman=0.0, min_dispersion=0.0)
    print(
        f"LANE 2 A/V vs TEXT: text_spearman={text_report.spearman:.3f} "
        f"av_spearman={av_report.spearman:.3f} delta={av_report.spearman - text_report.spearman:+.3f}"
    )
    assert av_report.spearman >= text_report.spearman

    # Calibration: run the production cutover gate (champion=text, challenger=A/V)
    # so founder reads the real promote/abstain decision + reason before locking
    # the gate's floors/margin at the P2-S7 checkpoint.
    cutover = evaluate_cutover(
        text_map,
        av_map,
        clips,
        min_spearman=0.0,
        min_dispersion=0.0,
        min_delta_spearman=0.0,
        min_n=3,
        n_bootstrap=1000,
    )
    print(
        f"LANE 2 CUTOVER: promoted={cutover.promoted} reason={cutover.reason} "
        f"delta={cutover.delta_spearman:+.3f} ci=({cutover.delta_ci_low:.3f},{cutover.delta_ci_high:.3f}) "
        f"mde={cutover.mde_estimate:.3f}"
    )
    assert isinstance(cutover.promoted, bool)
