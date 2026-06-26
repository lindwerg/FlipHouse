"""P3-C4 — caption_coverage telemetry: covered speech-time / clip wall-duration, fail-open."""

from __future__ import annotations

from fliphouse_worker.captioning.coverage import caption_coverage, coverage_from_words
from fliphouse_worker.captioning.segments import CaptionWord, slice_and_offset_words


def _seg(start: float, end: float, words: list[tuple[str, float, float]]) -> dict:
    return {
        "start": start,
        "end": end,
        "words": [{"word": w, "start": s, "end": e} for w, s, e in words],
    }


def test_full_window_is_fully_covered() -> None:
    segs = [_seg(0.0, 1.0, [(" a", 0.0, 1.0)])]
    assert caption_coverage(segs, (0.0, 1.0)) >= 0.95


def test_no_in_window_words_is_zero() -> None:
    segs = [_seg(0.0, 100.0, [(" a", 50.0, 51.0)])]
    assert caption_coverage(segs, (0.0, 10.0)) == 0.0


def test_partial_window_is_the_ratio() -> None:
    segs = [_seg(0.0, 30.0, [(" a", 0.0, 1.0)])]
    assert round(caption_coverage(segs, (0.0, 30.0)), 4) == 0.0333


def test_absolute_vs_relative_off_by_one_reads_as_zero() -> None:
    # The bug this metric exists to surface: speech is at absolute 10-11s but the window
    # was passed as the absolute 1010-1040 range → every word drops → coverage 0.0.
    segs = [_seg(0.0, 100.0, [(" a", 10.0, 11.0)])]
    assert caption_coverage(segs, (1010.0, 1040.0)) == 0.0


def test_overlapping_words_never_exceed_one() -> None:
    segs = [_seg(0.0, 3.0, [(" a", 0.0, 2.0), (" b", 1.0, 3.0)])]
    assert caption_coverage(segs, (0.0, 3.0)) == 1.0


def test_disjoint_words_sum_to_the_union_ratio() -> None:
    segs = [_seg(0.0, 10.0, [(" a", 0.0, 1.0), (" b", 5.0, 6.0)])]
    assert round(caption_coverage(segs, (0.0, 10.0)), 4) == 0.2  # (1 + 1) / 10


def test_malformed_inputs_fail_open_to_zero() -> None:
    assert caption_coverage([], (0.0, 10.0)) == 0.0
    assert caption_coverage("nope", (0.0, 10.0)) == 0.0
    assert caption_coverage([_seg(0.0, 10.0, [(" a", 0.0, 1.0)])], (40.0, 10.0)) == 0.0  # inverted
    assert caption_coverage([_seg(0.0, 10.0, [(" a", 0.0, 1.0)])], ("x", "y")) == 0.0  # type: ignore[arg-type]
    assert caption_coverage([_seg(0.0, 10.0, [(" a", 0.0, 1.0)])], (10.0,)) == 0.0  # type: ignore[arg-type]


def test_coverage_from_words_matches_caption_coverage() -> None:
    # The no-second-slice seam returns the same value when fed the canonical slice.
    segs = [_seg(0.0, 30.0, [(" a", 0.0, 1.0), (" b", 5.0, 6.0)])]
    window = (0.0, 30.0)
    words = slice_and_offset_words(segs, *window)
    assert coverage_from_words(words, window) == caption_coverage(segs, window)


def test_coverage_from_words_skips_non_floatable_timings() -> None:
    bad = [CaptionWord(text="a", start="x", end=1.0)]  # type: ignore[arg-type]
    assert coverage_from_words(bad, (0.0, 10.0)) == 0.0


def test_coverage_from_words_fails_open_on_a_malformed_window() -> None:
    words = [CaptionWord(text="a", start=0.0, end=1.0)]
    assert coverage_from_words(words, ("x", "y")) == 0.0  # type: ignore[arg-type]
    assert coverage_from_words(words, (10.0,)) == 0.0  # type: ignore[arg-type]
