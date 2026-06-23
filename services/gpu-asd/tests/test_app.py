"""app — synchronous signed /score ASGI: 200/400/401/404 + health, via fakes."""

import json

from fliphouse_asd.app import _MAX_BODY_BYTES, AppDeps, create_app

from ._fakes import drive, signed_headers

_SECRET = "shh"
_TS = "1700000000"


def _valid_body() -> bytes:
    return json.dumps(
        {
            "proxy_url": "https://example.com/proxy.mp4",
            "start": 0.0,
            "end": 1.0,
            "sample_fps": 2.0,
            "frames": [[{"x": 0, "y": 0, "w": 10, "h": 10}, {"x": 50, "y": 0, "w": 10, "h": 10}]],
        }
    ).encode("utf-8")


def _app(score_fn=None):
    fn = score_fn or (lambda req: tuple(tuple(0.5 for _ in fr) for fr in req.frames))
    return create_app(AppDeps(secret=_SECRET, score_fn=fn))


def test_score_returns_200_with_scores_on_valid_signed_request():
    body = _valid_body()
    app = _app(lambda req: ((0.9, 0.1),))
    status, payload = drive(
        app, "POST", "/score", body=body, headers=signed_headers(_SECRET, _TS, body)
    )
    assert status == 200
    assert payload == {"engine": "lr-asd", "scores": [[0.9, 0.1]]}


def test_score_rejects_bad_signature_with_401():
    body = _valid_body()
    bad = [(b"x-fliphouse-timestamp", _TS.encode()), (b"x-fliphouse-signature", b"sha256=bad")]
    status, payload = drive(_app(), "POST", "/score", body=body, headers=bad)
    assert status == 401
    assert payload == {"error": "invalid signature"}


def test_score_rejects_missing_signature_headers_with_401():
    body = _valid_body()
    status, payload = drive(_app(), "POST", "/score", body=body, headers=[])
    assert status == 401


def test_score_rejects_malformed_json_with_400():
    body = b"{not json"
    status, payload = drive(
        _app(), "POST", "/score", body=body, headers=signed_headers(_SECRET, _TS, body)
    )
    assert status == 400


def test_score_rejects_invalid_request_shape_with_400():
    body = json.dumps({"proxy_url": "https://x/p.mp4"}).encode("utf-8")
    status, payload = drive(
        _app(), "POST", "/score", body=body, headers=signed_headers(_SECRET, _TS, body)
    )
    assert status == 400
    assert "error" in payload


def test_score_maps_model_failure_to_500():
    body = _valid_body()

    def boom(req):
        raise RuntimeError("cuda oom")

    status, payload = drive(
        _app(boom), "POST", "/score", body=body, headers=signed_headers(_SECRET, _TS, body)
    )
    assert status == 500
    assert "LR-ASD scoring failed" in payload["error"]


def test_oversize_body_is_400():
    big = b"x" * (_MAX_BODY_BYTES + 1)
    status, payload = drive(
        _app(), "POST", "/score", body=big, headers=signed_headers(_SECRET, _TS, big)
    )
    assert status == 400
    assert "too large" in payload["error"]


def test_health_returns_ok():
    status, payload = drive(_app(), "GET", "/health")
    assert status == 200
    assert payload == {"status": "ok"}


def test_unknown_route_is_404():
    status, payload = drive(_app(), "GET", "/nope")
    assert status == 404
    assert payload == {"error": "not found"}
