"""parse_submit_request — required fields + https enforcement."""

from __future__ import annotations

import pytest

from fliphouse_gigaam.errors import InvalidSubmitRequest
from fliphouse_gigaam.validate import parse_submit_request

VALID = {
    "request_id": "r1",
    "audio_url": "https://r2.example/audio.wav",
    "language": "ru",
    "webhook_url": "https://receiver.example/gpu/callback",
    "output_prefix": "intermediate/h/asr",
}


def test_valid_body_parses():
    req = parse_submit_request(dict(VALID))
    assert req.request_id == "r1"
    assert req.audio_url == VALID["audio_url"]
    assert req.webhook_url == VALID["webhook_url"]


def test_non_object_body_rejected():
    with pytest.raises(InvalidSubmitRequest):
        parse_submit_request(["not", "a", "dict"])


@pytest.mark.parametrize("field", list(VALID))
def test_missing_field_rejected(field):
    body = dict(VALID)
    del body[field]
    with pytest.raises(InvalidSubmitRequest) as exc:
        parse_submit_request(body)
    assert field in str(exc.value)


def test_empty_field_rejected():
    body = dict(VALID, request_id="   ")
    with pytest.raises(InvalidSubmitRequest):
        parse_submit_request(body)


def test_non_string_field_rejected():
    body = dict(VALID, language=123)
    with pytest.raises(InvalidSubmitRequest):
        parse_submit_request(body)


@pytest.mark.parametrize("field", ["audio_url", "webhook_url"])
def test_non_https_url_rejected(field):
    body = dict(VALID, **{field: "http://insecure.example/x"})
    with pytest.raises(InvalidSubmitRequest) as exc:
        parse_submit_request(body)
    assert field in str(exc.value)
