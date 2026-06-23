"""contracts — frozen wire shapes + the canonical response projection."""

from fliphouse_asd.contracts import ENGINE_LR_ASD, FaceRef, ScoreRequest, ScoreResponse


def test_score_response_to_dict_lists_rows_with_engine():
    resp = ScoreResponse(scores=((0.9, 0.1), (0.2,)))
    assert resp.to_dict() == {"engine": ENGINE_LR_ASD, "scores": [[0.9, 0.1], [0.2]]}


def test_score_response_default_engine_is_lr_asd():
    assert ScoreResponse(scores=()).engine == ENGINE_LR_ASD


def test_face_ref_and_request_are_frozen_value_types():
    req = ScoreRequest(
        proxy_url="https://x/p.mp4",
        start=0.0,
        end=1.0,
        sample_fps=2.0,
        frames=((FaceRef(0.0, 0.0, 10.0, 10.0),),),
    )
    assert req.frames[0][0] == FaceRef(0.0, 0.0, 10.0, 10.0)
    assert req == ScoreRequest(
        proxy_url="https://x/p.mp4",
        start=0.0,
        end=1.0,
        sample_fps=2.0,
        frames=((FaceRef(0.0, 0.0, 10.0, 10.0),),),
    )
