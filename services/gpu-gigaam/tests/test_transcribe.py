"""transcribe_audio seam tests — pure GigaAM longform → contract mapping."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from fliphouse_gigaam.errors import TranscriptionError
from fliphouse_gigaam.transcribe import (
    _map_longform_result,
    payload_from_longform,
    transcribe_with_model,
)

from ._fakes import FakeModel


# Lightweight mirrors of the real gigaam ``LongformTranscriptionResult`` object
# graph (gigaam is not installed in CI). Attributes only — duck-typed match.
@dataclass(frozen=True)
class _FakeWord:
    text: str
    start: float
    end: float


@dataclass(frozen=True)
class _FakeSeg:
    text: str
    start: float
    end: float
    words: list | None


@dataclass(frozen=True)
class _FakeLongform:
    segments: list


def test_map_renames_text_to_word_and_offsets_times():
    # Window starts at 10.0s; word times are relative to the window.
    windows = [
        {
            "transcription": "привет мир",
            "boundaries": (10.0, 12.0),
            "words": [
                {"text": "привет", "start": 0.0, "end": 1.0},
                {"text": "мир", "start": 1.0, "end": 2.0},
            ],
        }
    ]

    payload = _map_longform_result(windows, language="ru")

    assert payload.language == "ru"
    assert payload.duration == 12.0  # max absolute segment end
    (seg,) = payload.segments
    assert seg.start == 10.0 and seg.end == 12.0
    assert seg.words[0].word == "привет"  # text → word
    assert seg.words[0].start == 10.0 and seg.words[0].end == 11.0  # offset applied
    assert seg.words[1].start == 11.0 and seg.words[1].end == 12.0


def test_map_two_windows_duration_is_latest_end():
    windows = [
        {"boundaries": (0.0, 5.0), "words": [{"text": "a", "start": 0.0, "end": 1.0}]},
        {"boundaries": (5.0, 9.0), "words": [{"text": "b", "start": 0.0, "end": 1.0}]},
    ]
    payload = _map_longform_result(windows, language="ru")
    assert payload.duration == 9.0
    assert len(payload.segments) == 2
    assert payload.segments[1].words[0].start == 5.0  # offset = second window start


def test_map_window_missing_boundaries_defaults_to_zero():
    windows = [{"words": [{"text": "a", "start": 0.0, "end": 1.0}]}]
    payload = _map_longform_result(windows, language="ru")
    assert payload.segments[0].start == 0.0
    assert payload.duration == 0.0


def test_map_empty_windows_yields_empty_payload():
    payload = _map_longform_result([], language="ru")
    assert payload.duration == 0.0
    assert payload.segments == ()


def test_transcribe_with_model_runs_and_maps():
    model = FakeModel(
        windows=[{"boundaries": (0.0, 1.0), "words": [{"text": "x", "start": 0.0, "end": 1.0}]}]
    )
    payload = transcribe_with_model(model, "/tmp/audio.wav", "ru")
    assert model.seen_path == "/tmp/audio.wav"
    assert payload.segments[0].words[0].word == "x"


def test_transcribe_with_model_wraps_model_failure():
    model = FakeModel(raises=RuntimeError("cuda oom"))
    with pytest.raises(TranscriptionError) as exc:
        transcribe_with_model(model, "/tmp/audio.wav", "ru")
    assert "cuda oom" in str(exc.value)


def test_payload_from_longform_keeps_absolute_times_and_renames_text():
    # The REAL longform result: object graph with ALREADY-ABSOLUTE word times.
    result = _FakeLongform(
        segments=[
            _FakeSeg(
                text="привет мир",
                start=10.0,
                end=12.0,
                words=[
                    _FakeWord(text="привет", start=10.0, end=11.0),
                    _FakeWord(text="мир", start=11.0, end=12.0),
                ],
            )
        ]
    )

    payload = payload_from_longform(result, language="ru")

    assert payload.language == "ru"
    assert payload.duration == 12.0  # latest absolute segment end
    (seg,) = payload.segments
    assert seg.start == 10.0 and seg.end == 12.0
    assert seg.words[0].word == "привет"  # .text → .word, NO offset re-added
    assert seg.words[0].start == 10.0 and seg.words[0].end == 11.0
    assert seg.words[1].start == 11.0 and seg.words[1].end == 12.0


def test_payload_from_longform_two_segments_duration_is_latest_end():
    result = _FakeLongform(
        segments=[
            _FakeSeg(text="a", start=0.0, end=5.0, words=[_FakeWord("a", 0.0, 1.0)]),
            _FakeSeg(text="b", start=5.0, end=9.0, words=[_FakeWord("b", 5.0, 6.0)]),
        ]
    )
    payload = payload_from_longform(result, language="ru")
    assert payload.duration == 9.0
    assert len(payload.segments) == 2
    assert payload.segments[1].words[0].start == 5.0  # absolute, not re-offset


def test_payload_from_longform_segment_without_words_is_empty_tuple():
    result = _FakeLongform(segments=[_FakeSeg(text="", start=0.0, end=2.0, words=None)])
    payload = payload_from_longform(result, language="ru")
    assert payload.segments[0].words == ()
    assert payload.duration == 2.0


def test_payload_from_longform_empty_segments_yields_empty_payload():
    payload = payload_from_longform(_FakeLongform(segments=[]), language="ru")
    assert payload.duration == 0.0
    assert payload.segments == ()
