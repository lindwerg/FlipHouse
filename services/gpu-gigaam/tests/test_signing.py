"""Signing tests — the HMAC framing must match what the receiver recomputes."""

from __future__ import annotations

import hashlib
import hmac

from fliphouse_gigaam.signing import (
    SIGNATURE_HEADER,
    SIGNATURE_PREFIX,
    TIMESTAMP_HEADER,
    compute_signature,
    sign_request,
)

SECRET = "test-secret"


def _receiver_recompute(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Independent recomputation, exactly as the webhook-receiver verifies it:
    hex(hmacSHA256(secret, `${timestamp}.${rawBody}`)) with a sha256= prefix."""
    message = f"{timestamp}.".encode() + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def test_compute_signature_matches_independent_recomputation():
    # Arrange
    timestamp = "1700000000"
    raw_body = b'{"request_id":"r1","status":"succeeded"}'

    # Act
    signature = compute_signature(SECRET, timestamp, raw_body)

    # Assert — byte-for-byte the value the receiver will compute.
    assert signature == _receiver_recompute(SECRET, timestamp, raw_body)
    assert signature.startswith(SIGNATURE_PREFIX)


def test_compute_signature_binds_timestamp_into_message():
    raw_body = b"{}"
    sig_a = compute_signature(SECRET, "1", raw_body)
    sig_b = compute_signature(SECRET, "2", raw_body)
    assert sig_a != sig_b  # timestamp is part of the signed message


def test_compute_signature_covers_cyrillic_body_bytes():
    raw_body = '{"word":"привет"}'.encode()
    timestamp = "1700000000"
    assert compute_signature(SECRET, timestamp, raw_body) == _receiver_recompute(
        SECRET, timestamp, raw_body
    )


def test_sign_request_sets_both_headers_and_keeps_body_verbatim():
    # Arrange
    timestamp = "1700000000"
    raw_body = b'{"k":"v"}'

    # Act
    signed = sign_request(SECRET, timestamp, raw_body)

    # Assert
    assert signed.body == raw_body  # exact bytes preserved
    assert signed.headers[TIMESTAMP_HEADER] == timestamp
    assert signed.headers[SIGNATURE_HEADER] == compute_signature(SECRET, timestamp, raw_body)
    assert signed.headers["content-type"] == "application/json"
