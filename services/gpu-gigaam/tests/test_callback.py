"""sign_and_post tests — real body framing + HMAC, network seam faked."""

from __future__ import annotations

import hashlib
import hmac
import json

import pytest

from fliphouse_gigaam.callback import (
    build_failure_body,
    build_success_body,
    sign_and_post,
)
from fliphouse_gigaam.errors import CallbackPostError
from fliphouse_gigaam.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER

from ._fakes import FakePoster, canned_payload

SECRET = "test-secret"
URL = "https://receiver.example/gpu/callback"


def _receiver_verify(secret: str, body: bytes, headers: dict[str, str]) -> bool:
    """Re-run the receiver's verification on the captured POST."""
    ts = headers[TIMESTAMP_HEADER]
    message = f"{ts}.".encode() + body
    expected = "sha256=" + hmac.new(secret.encode(), message, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers[SIGNATURE_HEADER])


def test_success_body_shape():
    body = build_success_body("r1", canned_payload())
    assert body["request_id"] == "r1"
    assert body["status"] == "succeeded"
    assert body["engine"] == "gigaam-v3"
    assert body["payload"]["language"] == "ru"
    assert body["payload"]["segments"][0]["words"][0]["word"] == "привет"


def test_failure_body_shape():
    body = build_failure_body("r1", "boom")
    assert body == {"request_id": "r1", "status": "failed", "error": "boom"}


def test_sign_and_post_signs_exact_bytes_receiver_can_verify():
    poster = FakePoster(status_code=202)
    body = build_success_body("r1", canned_payload())

    sign_and_post(poster=poster, secret=SECRET, webhook_url=URL, body=body, timestamp="1700000000")

    url, sent_body, headers = poster.calls[0]
    assert url == URL
    # The receiver verifies over the EXACT bytes that were POSTed.
    assert _receiver_verify(SECRET, sent_body, headers)
    # And those bytes decode back to the contract body.
    assert json.loads(sent_body)["payload"]["duration"] == 2.0


def test_sign_and_post_uses_compact_utf8_serialization():
    poster = FakePoster()
    sign_and_post(
        poster=poster,
        secret=SECRET,
        webhook_url=URL,
        body=build_success_body("r1", canned_payload()),
        timestamp="1",
    )
    _url, sent_body, _headers = poster.calls[0]
    assert b" " not in sent_body  # compact separators
    assert "привет".encode() in sent_body  # ensure_ascii=False


def test_sign_and_post_raises_on_non_2xx():
    poster = FakePoster(status_code=500)
    with pytest.raises(CallbackPostError) as exc:
        sign_and_post(
            poster=poster,
            secret=SECRET,
            webhook_url=URL,
            body=build_failure_body("r1", "x"),
            timestamp="1",
        )
    assert "500" in str(exc.value)


def test_sign_and_post_wraps_transport_error():
    poster = FakePoster(raises=ConnectionError("refused"))
    with pytest.raises(CallbackPostError) as exc:
        sign_and_post(
            poster=poster,
            secret=SECRET,
            webhook_url=URL,
            body=build_failure_body("r1", "x"),
            timestamp="1",
        )
    assert "refused" in str(exc.value)
