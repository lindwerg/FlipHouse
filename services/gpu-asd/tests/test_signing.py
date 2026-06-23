"""signing — HMAC compute + constant-time verify (mirrors the worker's signer)."""

from fliphouse_asd.signing import (
    SIGNATURE_PREFIX,
    compute_signature,
    verify_signature,
)


def test_compute_signature_is_deterministic_and_prefixed():
    sig = compute_signature("secret", "1700000000", b'{"a":1}')
    assert sig.startswith(SIGNATURE_PREFIX)
    assert sig == compute_signature("secret", "1700000000", b'{"a":1}')


def test_compute_signature_changes_with_body_timestamp_and_secret():
    base = compute_signature("secret", "1700000000", b"body")
    assert base != compute_signature("secret", "1700000001", b"body")
    assert base != compute_signature("secret", "1700000000", b"other")
    assert base != compute_signature("other", "1700000000", b"body")


def test_verify_accepts_a_matching_signature():
    ts, body = "1700000000", b'{"x":1}'
    sig = compute_signature("secret", ts, body)
    assert verify_signature("secret", ts, body, sig) is True


def test_verify_rejects_a_tampered_body():
    ts = "1700000000"
    sig = compute_signature("secret", ts, b"original")
    assert verify_signature("secret", ts, b"tampered", sig) is False


def test_verify_rejects_blank_signature():
    assert verify_signature("secret", "1700000000", b"body", "") is False
