"""Unit tests for the pure clip-window word slicer (slice + offset + lstrip)."""

from __future__ import annotations

import pytest

from fliphouse_worker.captioning.segments import (
    CaptionWord,
    enforce_monotonic_starts,
    slice_and_offset_words,
)


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


# --- P3-C3: monotonic word-start clamp -------------------------------------------------


def test_decreasing_starts_become_non_decreasing_text_intact() -> None:
    words = [
        CaptionWord(text="a", start=5.0, end=5.4),
        CaptionWord(text="b", start=2.0, end=2.5),
        CaptionWord(text="c", start=6.0, end=6.3),
    ]
    out = enforce_monotonic_starts(words)
    assert [w.start for w in out] == [5.0, 5.0, 6.0]
    assert [w.text for w in out] == ["a", "b", "c"]  # text + order untouched


def test_equal_starts_are_preserved() -> None:
    words = [CaptionWord(text="a", start=3.0, end=3.2), CaptionWord(text="b", start=3.0, end=3.4)]
    assert enforce_monotonic_starts(words) == words


def test_already_monotonic_is_returned_unchanged() -> None:
    words = [CaptionWord(text="a", start=0.0, end=0.5), CaptionWord(text="b", start=1.0, end=1.4)]
    out = enforce_monotonic_starts(words)
    assert out == words
    assert all(a is b for a, b in zip(out, words, strict=True))  # same objects, no churn


def test_end_is_lifted_to_keep_end_ge_start() -> None:
    # A backwards word whose end falls before the clamped start gets its end lifted too.
    words = [CaptionWord(text="a", start=5.0, end=5.4), CaptionWord(text="b", start=1.0, end=1.5)]
    out = enforce_monotonic_starts(words)
    assert out[1].start == 5.0
    assert out[1].end == 5.0  # end lifted to the clamped start (was 1.5 < 5.0)
    assert all(w.end >= w.start for w in out)


def test_clamped_word_keeps_its_own_later_end() -> None:
    # When a backwards word's END is LATER than the clamped start, the end is preserved
    # (only lifted when it would fall below the new start).
    words = [CaptionWord(text="a", start=5.0, end=5.4), CaptionWord(text="b", start=2.0, end=8.0)]
    out = enforce_monotonic_starts(words)
    assert out[1].start == 5.0
    assert out[1].end == 8.0  # speaker's real end kept (8.0 > clamped start 5.0)


def test_enforce_monotonic_empty_is_empty() -> None:
    assert enforce_monotonic_starts([]) == []


def test_slice_emits_monotonic_starts_on_cross_talk() -> None:
    # Cross-talk: the second word starts BEFORE the first → slicing clamps it up.
    word_segments = [_seg(0.0, 20.0, [(" later", 10.0, 10.4), (" earlier", 6.0, 6.3)])]
    out = slice_and_offset_words(word_segments, 0.0, 20.0)
    assert [w.start for w in out] == [10.0, 10.0]
    assert [w.text for w in out] == ["later", "earlier"]
    assert all(w.end >= w.start for w in out)


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
