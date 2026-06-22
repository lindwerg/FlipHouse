"""Unit tests for the pure clip-window word slicer (slice + offset + lstrip)."""

from __future__ import annotations

import pytest

from fliphouse_worker.captioning.segments import CaptionWord, slice_and_offset_words


def _seg(start: float, end: float, words: list[tuple[str, float, float]]) -> dict:
    return {
        "start": start,
        "end": end,
        "words": [{"word": w, "start": s, "end": e} for w, s, e in words],
    }


def test_slices_only_words_inside_the_closed_open_window() -> None:
    word_segments = [
        _seg(0.0, 10.0, [(" привет", 1.0, 2.0), (" мир", 5.0, 6.0), (" вне", 12.0, 13.0)])
    ]
    # window [4, 8): " мир" at [5,6) is inside; " привет" before; " вне" after.
    out = slice_and_offset_words(word_segments, 4.0, 8.0)
    assert out == [CaptionWord(text="мир", start=1.0, end=2.0)]


def test_offsets_words_to_clip_relative_zero() -> None:
    word_segments = [_seg(0.0, 30.0, [(" a", 10.0, 10.5), (" b", 11.0, 11.4)])]
    out = slice_and_offset_words(word_segments, 10.0, 20.0)
    assert out == [
        CaptionWord(text="a", start=0.0, end=0.5),
        CaptionWord(text="b", start=1.0, end=1.4),
    ]


def test_lstrips_the_leading_space_token_before_measuring() -> None:
    # The captacity LEADING-SPACE convention must be stripped or \k widths are wrong.
    word_segments = [_seg(0.0, 5.0, [(" слово", 1.0, 2.0)])]
    out = slice_and_offset_words(word_segments, 0.0, 5.0)
    assert out == [CaptionWord(text="слово", start=1.0, end=2.0)]


def test_closed_open_boundary_includes_start_excludes_end() -> None:
    word_segments = [_seg(0.0, 20.0, [(" at_start", 5.0, 5.5), (" at_end", 15.0, 15.5)])]
    # window [5, 15): start word at exactly 5.0 is IN; end word at exactly 15.0 is OUT.
    out = slice_and_offset_words(word_segments, 5.0, 15.0)
    assert [w.text for w in out] == ["at_start"]


def test_drops_a_word_with_empty_text_after_lstrip() -> None:
    word_segments = [_seg(0.0, 5.0, [("   ", 1.0, 2.0), (" ok", 2.0, 3.0)])]
    out = slice_and_offset_words(word_segments, 0.0, 5.0)
    assert [w.text for w in out] == ["ok"]


def test_clamps_a_negative_offset_to_zero() -> None:
    # A word starting just before the clip start (rounding slop) clamps to t=0.
    word_segments = [_seg(0.0, 20.0, [(" w", 9.99, 11.0)])]
    out = slice_and_offset_words(word_segments, 10.0, 20.0)
    # 9.99 < 10.0 → outside [10,20) → dropped (closed-open on start).
    assert out == []


def test_fail_open_returns_empty_on_malformed_input() -> None:
    assert slice_and_offset_words([{"words": "nope"}], 0.0, 10.0) == []
    assert slice_and_offset_words([{"start": 0.0}], 0.0, 10.0) == []
    assert slice_and_offset_words("garbage", 0.0, 10.0) == []  # type: ignore[arg-type]


def test_fail_open_skips_a_non_mapping_segment_in_the_list() -> None:
    word_segments = ["not-a-dict", _seg(0.0, 10.0, [(" ok", 1.0, 2.0)])]
    out = slice_and_offset_words(word_segments, 0.0, 10.0)
    assert [w.text for w in out] == ["ok"]


def test_fail_open_skips_a_non_mapping_word() -> None:
    word_segments = [
        {
            "start": 0.0,
            "end": 10.0,
            "words": ["raw-string", {"word": " ok", "start": 1.0, "end": 2.0}],
        }
    ]
    out = slice_and_offset_words(word_segments, 0.0, 10.0)
    assert [w.text for w in out] == ["ok"]


def test_fail_open_skips_a_word_with_non_numeric_timing() -> None:
    word_segments = [
        {"start": 0.0, "end": 10.0, "words": [{"word": " bad", "start": "x", "end": 2.0}]}
    ]
    assert slice_and_offset_words(word_segments, 0.0, 10.0) == []


def test_empty_word_segments_is_empty() -> None:
    assert slice_and_offset_words([], 0.0, 10.0) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
