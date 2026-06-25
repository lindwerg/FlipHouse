"""Fail-loud validator for the GigaAM-v3 GPU raw payload (the webhook delivery).

The GPU GigaAM service produces its result on the GPU lane and delivers it via
webhook; the ``asr-finalize`` CLI step downloads that raw JSON from R2 and hands
it here BEFORE :func:`normalize_segments` runs. This module is the single gate
that refuses ANY drift from the agreed contract:

    {
      "duration": <float seconds ≥ 0>,
      "language": "ru",
      "segments": [
        {"start": <float>, "end": <float>,
         "text": <str, OPTIONAL — punctuated/normalized segment text>,
         "words": [{"word": <str>, "start": <float>, "end": <float>}]}
      ]
    }

The per-word ``"word"`` key is the bare token; the OPTIONAL segment-level ``"text"``
carries the model's PUNCTUATED/normalized transcription (GigaAM v3 ``e2e_rnnt``
emits punctuation at the segment level, not on words — TRANS-1). ``text`` is
additive: absent on the legacy payload, a non-string ``text`` fails loud (drift),
and ``normalize_segments`` consumes it to recover sentence boundaries.

The most likely version-drift footgun is a renamed/absent per-word ``"word"``
key. That MUST fail loud here (a named :class:`GigaamPayloadError`) instead of
silently degrading downstream (e.g. a per-word ``"text"`` rename). :class:`GigaamPayloadError`
subclasses :class:`ValueError` so the CLI dispatcher classifies it as fatal
(don't-retry) — a malformed payload will never become valid on retry.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass


class GigaamPayloadError(ValueError):
    """Raised when the GPU raw payload drifts from the agreed contract shape."""


@dataclass(frozen=True)
class ValidatedPayload:
    """The validated raw payload, ready to hand to ``normalize_segments``.

    ``segments`` is returned verbatim (the same list of mappings the payload
    carried) because :func:`normalize_segments` consumes exactly that shape; the
    validation guarantees every element is well-formed.
    """

    duration: float
    language: str
    segments: list[Mapping]


def _is_number(value: object) -> bool:
    """True for a real, finite int/float — bool is rejected (drift, not a number)."""
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _validate_word(word: object, *, seg_index: int, word_index: int) -> None:
    where = f"segment {seg_index} word {word_index}"
    if not isinstance(word, Mapping):
        raise GigaamPayloadError(f"{where} must be a mapping")
    if "word" not in word:
        raise GigaamPayloadError(f"{where} missing 'word' key (version drift?)")
    if not isinstance(word["word"], str):
        raise GigaamPayloadError(f"{where} 'word' must be a string")
    for time_key in ("start", "end"):
        if not _is_number(word.get(time_key)):
            raise GigaamPayloadError(f"{where} '{time_key}' must be a number")


def _validate_segment(segment: object, *, index: int) -> None:
    if not isinstance(segment, Mapping):
        raise GigaamPayloadError(f"segment {index} must be a mapping")
    # Optional punctuated segment text (TRANS-1): absent is fine, present must be a
    # string — a non-string is drift and fails loud rather than silently degrading.
    if "text" in segment and not isinstance(segment["text"], str):
        raise GigaamPayloadError(f"segment {index} 'text' must be a string")
    words = segment.get("words")
    if not isinstance(words, list):
        raise GigaamPayloadError(f"segment {index} missing 'words' list")
    for word_index, word in enumerate(words):
        _validate_word(word, seg_index=index, word_index=word_index)


def validate_gigaam_payload(payload: Mapping) -> ValidatedPayload:
    """Validate the GPU raw payload, raising :class:`GigaamPayloadError` on any drift.

    ``language`` defaults to ``"ru"`` when absent (the only language the GPU lane
    serves); ``duration`` and ``segments`` are mandatory and fully checked.
    """
    if not isinstance(payload, Mapping):
        raise GigaamPayloadError("payload must be a mapping")

    duration = payload.get("duration")
    if not _is_number(duration) or duration < 0:
        raise GigaamPayloadError("duration must be a finite number ≥ 0")

    segments = payload.get("segments")
    if not isinstance(segments, list):
        raise GigaamPayloadError("segments must be a list")
    for index, segment in enumerate(segments):
        _validate_segment(segment, index=index)

    language = payload.get("language", "ru")
    if not isinstance(language, str):
        raise GigaamPayloadError("language must be a string")

    return ValidatedPayload(duration=float(duration), language=language, segments=segments)
