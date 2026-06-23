"""scoring — model-seam orchestration: shape validation + clamp + typed errors."""

import pytest

from fliphouse_asd.contracts import ENGINE_LR_ASD, FaceRef, ScoreRequest
from fliphouse_asd.errors import ScoringError
from fliphouse_asd.scoring import run_scoring


def _req(frames) -> ScoreRequest:
    return ScoreRequest(
        proxy_url="https://example.com/p.mp4",
        start=0.0,
        end=1.0,
        sample_fps=2.0,
        frames=frames,
    )


def test_run_scoring_returns_clamped_grid_with_engine_tag():
    req = _req(((FaceRef(0, 0, 10, 10), FaceRef(20, 0, 10, 10)),))
    resp = run_scoring(req, lambda r: ((0.9, 0.1),))
    assert resp.engine == ENGINE_LR_ASD
    assert resp.scores == ((0.9, 0.1),)


def test_run_scoring_clamps_out_of_range_scores():
    req = _req(((FaceRef(0, 0, 10, 10), FaceRef(20, 0, 10, 10)),))
    resp = run_scoring(req, lambda r: ((5.0, -3.0),))
    assert resp.scores == ((1.0, 0.0),)


def test_run_scoring_passes_the_request_to_the_seam():
    req = _req(((FaceRef(0, 0, 10, 10),),))
    seen = {}

    def fn(r):
        seen["req"] = r
        return ((0.5,),)

    run_scoring(req, fn)
    assert seen["req"] is req


def test_run_scoring_raises_on_seam_failure():
    req = _req(((FaceRef(0, 0, 10, 10),),))

    def boom(r):
        raise RuntimeError("cuda oom")

    with pytest.raises(ScoringError, match="cuda oom"):
        run_scoring(req, boom)


def test_run_scoring_raises_on_wrong_frame_count():
    req = _req(((FaceRef(0, 0, 10, 10),), (FaceRef(0, 0, 10, 10),)))
    with pytest.raises(ScoringError, match="does not match"):
        run_scoring(req, lambda r: ((0.5,),))  # one row for two frames


def test_run_scoring_raises_on_wrong_face_count():
    req = _req(((FaceRef(0, 0, 10, 10), FaceRef(20, 0, 10, 10)),))
    with pytest.raises(ScoringError, match="does not match"):
        run_scoring(req, lambda r: ((0.5,),))  # one score for two faces


def test_run_scoring_handles_empty_frames():
    resp = run_scoring(_req(()), lambda r: ())
    assert resp.scores == ()
