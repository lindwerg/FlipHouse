"""validate_gigaam_payload — fail-loud contract guard for the GPU raw payload.

The GPU GigaAM service delivers its result via webhook; this validator is the
single gate that refuses any drift from the agreed shape BEFORE normalize runs.
The most likely version-drift footgun (a missing per-word ``"word"`` key) must
fail loud here rather than silently degrade downstream.
"""

from __future__ import annotations

import math

import pytest

from fliphouse_worker.transcription.raw_payload import (
    GigaamPayloadError,
    ValidatedPayload,
    validate_gigaam_payload,
)

_VALID = {
    "duration": 2.0,
    "language": "ru",
    "segments": [
        {
            "start": 0.0,
            "end": 2.0,
            "words": [
                {"word": "Я", "start": 0.0, "end": 0.4},
                {"word": "потерял", "start": 0.4, "end": 2.0},
            ],
        },
    ],
}


def test_valid_payload_returns_segments_duration_language():
    result = validate_gigaam_payload(_VALID)
    assert isinstance(result, ValidatedPayload)
    assert result.duration == 2.0
    assert result.language == "ru"
    assert result.segments == _VALID["segments"]


def test_valid_payload_with_empty_segments_is_accepted():
    result = validate_gigaam_payload({"duration": 0.0, "language": "ru", "segments": []})
    assert result.segments == []
    assert result.duration == 0.0


def test_language_defaults_to_ru_when_absent():
    result = validate_gigaam_payload({"duration": 1.0, "segments": []})
    assert result.language == "ru"


def test_non_str_language_raises():
    with pytest.raises(GigaamPayloadError, match="language must be a string"):
        validate_gigaam_payload({"duration": 1.0, "language": 7, "segments": []})


def test_non_mapping_payload_raises():
    with pytest.raises(GigaamPayloadError, match="payload must be a mapping"):
        validate_gigaam_payload([])  # type: ignore[arg-type]


def test_missing_duration_raises():
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"language": "ru", "segments": []})


def test_non_numeric_duration_raises():
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"duration": "2.0", "segments": []})


def test_negative_duration_raises():
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"duration": -1.0, "segments": []})


def test_non_finite_duration_raises():
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"duration": math.inf, "segments": []})
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"duration": math.nan, "segments": []})


def test_bool_duration_raises():
    # bool is an int subclass; a True/False duration is drift, not a number.
    with pytest.raises(GigaamPayloadError, match="duration"):
        validate_gigaam_payload({"duration": True, "segments": []})


def test_missing_segments_raises():
    with pytest.raises(GigaamPayloadError, match="segments"):
        validate_gigaam_payload({"duration": 1.0})


def test_non_list_segments_raises():
    with pytest.raises(GigaamPayloadError, match="segments must be a list"):
        validate_gigaam_payload({"duration": 1.0, "segments": {}})


def test_non_mapping_segment_raises():
    with pytest.raises(GigaamPayloadError, match="segment 0 must be a mapping"):
        validate_gigaam_payload({"duration": 1.0, "segments": ["nope"]})


def test_segment_missing_words_raises():
    with pytest.raises(GigaamPayloadError, match="segment 0 missing 'words' list"):
        validate_gigaam_payload({"duration": 1.0, "segments": [{"start": 0.0, "end": 1.0}]})


def test_segment_optional_text_string_is_accepted_and_passed_through():
    # The punctuated/normalized segment text (TRANS-1) is OPTIONAL but, when a
    # string, must validate and survive verbatim onto normalize_segments.
    payload = {
        "duration": 1.0,
        "language": "ru",
        "segments": [
            {
                "start": 0.0,
                "end": 1.0,
                "text": "Привет.",
                "words": [{"word": "привет", "start": 0.0, "end": 1.0}],
            }
        ],
    }
    result = validate_gigaam_payload(payload)
    assert result.segments[0]["text"] == "Привет."


def test_segment_non_str_text_raises():
    # A non-string segment "text" is drift and must fail loud.
    payload = {
        "duration": 1.0,
        "segments": [{"text": 7, "words": [{"word": "x", "start": 0.0, "end": 1.0}]}],
    }
    with pytest.raises(GigaamPayloadError, match="segment 0 'text' must be a string"):
        validate_gigaam_payload(payload)


def test_segment_non_list_words_raises():
    with pytest.raises(GigaamPayloadError, match="segment 0 missing 'words' list"):
        validate_gigaam_payload({"duration": 1.0, "segments": [{"words": {}}]})


def test_word_missing_word_key_fails_loud_not_silent_text_fallback():
    # The headline version-drift footgun: a renamed/absent "word" key must FAIL,
    # never silently fall back to "text".
    payload = {
        "duration": 1.0,
        "segments": [{"words": [{"start": 0.0, "end": 1.0, "text": "Я"}]}],
    }
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 missing 'word'"):
        validate_gigaam_payload(payload)


def test_word_non_str_word_raises():
    payload = {"duration": 1.0, "segments": [{"words": [{"word": 5, "start": 0.0, "end": 1.0}]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'word' must be a string"):
        validate_gigaam_payload(payload)


def test_word_non_mapping_raises():
    payload = {"duration": 1.0, "segments": [{"words": ["nope"]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 must be a mapping"):
        validate_gigaam_payload(payload)


def test_word_missing_start_raises():
    payload = {"duration": 1.0, "segments": [{"words": [{"word": "Я", "end": 1.0}]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'start' must be a number"):
        validate_gigaam_payload(payload)


def test_word_missing_end_raises():
    payload = {"duration": 1.0, "segments": [{"words": [{"word": "Я", "start": 0.0}]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'end' must be a number"):
        validate_gigaam_payload(payload)


def test_word_non_numeric_time_raises():
    payload = {"duration": 1.0, "segments": [{"words": [{"word": "Я", "start": "0", "end": 1.0}]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'start' must be a number"):
        validate_gigaam_payload(payload)


def test_word_bool_time_raises():
    payload = {"duration": 1.0, "segments": [{"words": [{"word": "Я", "start": True, "end": 1.0}]}]}
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'start' must be a number"):
        validate_gigaam_payload(payload)


def test_word_non_finite_time_raises():
    payload = {
        "duration": 1.0,
        "segments": [{"words": [{"word": "Я", "start": 0.0, "end": math.inf}]}],
    }
    with pytest.raises(GigaamPayloadError, match="segment 0 word 0 'end' must be a number"):
        validate_gigaam_payload(payload)


def test_gigaam_payload_error_is_value_error():
    # So cli/_dispatch.classify_exception maps it to fatal VALUE_ERROR (no retry).
    assert issubclass(GigaamPayloadError, ValueError)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
