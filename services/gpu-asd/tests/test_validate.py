"""validate — pure /score body validation → ScoreRequest."""

import pytest

from fliphouse_asd.contracts import FaceRef
from fliphouse_asd.errors import InvalidScoreRequest
from fliphouse_asd.validate import parse_score_request


def _body(**overrides) -> dict:
    body = {
        "proxy_url": "https://example.com/proxy.mp4",
        "start": 0.0,
        "end": 1.0,
        "sample_fps": 2.0,
        "frames": [[{"x": 0, "y": 0, "w": 10, "h": 10}]],
    }
    body.update(overrides)
    return body


def test_parses_a_valid_body():
    req = parse_score_request(_body())
    assert req.proxy_url == "https://example.com/proxy.mp4"
    assert req.start == 0.0 and req.end == 1.0 and req.sample_fps == 2.0
    assert req.frames == ((FaceRef(0.0, 0.0, 10.0, 10.0),),)


def test_parses_empty_frame_and_empty_frames():
    req = parse_score_request(_body(frames=[[]]))
    assert req.frames == ((),)
    assert parse_score_request(_body(frames=[])).frames == ()


def test_rejects_non_object_body():
    with pytest.raises(InvalidScoreRequest, match="JSON object"):
        parse_score_request([1, 2, 3])


def test_rejects_missing_or_non_https_proxy_url():
    with pytest.raises(InvalidScoreRequest, match="proxy_url"):
        parse_score_request(_body(proxy_url="  "))
    with pytest.raises(InvalidScoreRequest, match="https"):
        parse_score_request(_body(proxy_url="http://example.com/p.mp4"))


def test_rejects_non_numeric_window_fields():
    with pytest.raises(InvalidScoreRequest, match="start must be a number"):
        parse_score_request(_body(start="x"))
    # bool must not slip through as an int.
    with pytest.raises(InvalidScoreRequest, match="end must be a number"):
        parse_score_request(_body(end=True))


def test_rejects_bad_window_and_fps():
    with pytest.raises(InvalidScoreRequest, match="end must be greater"):
        parse_score_request(_body(start=2.0, end=1.0))
    with pytest.raises(InvalidScoreRequest, match="sample_fps must be positive"):
        parse_score_request(_body(sample_fps=0.0))


def test_rejects_bad_frames_shapes():
    with pytest.raises(InvalidScoreRequest, match="frames must be a list"):
        parse_score_request(_body(frames="nope"))
    with pytest.raises(InvalidScoreRequest, match="frame 0 must be a list"):
        parse_score_request(_body(frames=[{"x": 0}]))
    with pytest.raises(InvalidScoreRequest, match="face 0 must be an object"):
        parse_score_request(_body(frames=[[5]]))


def test_rejects_bad_face_coords():
    with pytest.raises(InvalidScoreRequest, match="x must be a number"):
        parse_score_request(_body(frames=[[{"x": "a", "y": 0, "w": 1, "h": 1}]]))
    with pytest.raises(InvalidScoreRequest, match="negative size"):
        parse_score_request(_body(frames=[[{"x": 0, "y": 0, "w": -1, "h": 1}]]))
