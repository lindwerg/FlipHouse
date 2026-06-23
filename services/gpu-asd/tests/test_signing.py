"""signing — HMAC compute + constant-time verify + timestamp replay window.

Every ``verify_signature`` call pins the clock to ``_NOW`` (the signed timestamp) so the
replay-window check is deterministic and the offline suite never touches ``time.time``.
"""

from fliphouse_asd.signing import (
    MAX_TIMESTAMP_AGE_S,
    SIGNATURE_PREFIX,
    compute_signature,
    is_timestamp_fresh,
    verify_signature,
)

_TS = "1700000000"
_NOW = float(_TS)


def _now(value: float = _NOW):
    return lambda: value


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
    body = b'{"x":1}'
    sig = compute_signature("secret", _TS, body)
    assert verify_signature("secret", _TS, body, sig, now=_now()) is True


def test_verify_rejects_a_tampered_body():
    sig = compute_signature("secret", _TS, b"original")
    assert verify_signature("secret", _TS, b"tampered", sig, now=_now()) is False


def test_verify_rejects_blank_signature():
    assert verify_signature("secret", _TS, b"body", "", now=_now()) is False


def test_verify_rejects_stale_timestamp_even_with_valid_signature():
    # A correctly-signed request stamped far in the PAST is a replay → False (→ 401).
    body = b'{"x":1}'
    sig = compute_signature("secret", _TS, body)
    stale_clock = _now(_NOW + MAX_TIMESTAMP_AGE_S + 1.0)
    assert verify_signature("secret", _TS, body, sig, now=stale_clock) is False


def test_verify_rejects_future_skewed_timestamp():
    # Skew in the OTHER direction (timestamp ahead of our clock) is rejected too.
    body = b'{"x":1}'
    sig = compute_signature("secret", _TS, body)
    past_clock = _now(_NOW - MAX_TIMESTAMP_AGE_S - 1.0)
    assert verify_signature("secret", _TS, body, sig, now=past_clock) is False


def test_is_timestamp_fresh_accepts_value_within_window():
    assert is_timestamp_fresh(_TS, now=_now(_NOW + MAX_TIMESTAMP_AGE_S)) is True


def test_is_timestamp_fresh_rejects_value_outside_window():
    assert is_timestamp_fresh(_TS, now=_now(_NOW + MAX_TIMESTAMP_AGE_S + 0.1)) is False


def test_is_timestamp_fresh_rejects_blank_and_non_numeric():
    assert is_timestamp_fresh("   ", now=_now()) is False
    assert is_timestamp_fresh("not-a-number", now=_now()) is False
