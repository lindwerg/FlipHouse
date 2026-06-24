"""Unit coverage for engine/align.py — verbatim phrase → word-timestamp alignment.

The module is PURE and fail-open: the fuzzy matcher (RapidFuzz in production) is
injected via ``align_fn`` and NEVER imported here. These tests exercise every line
with a synthetic ``align_fn`` stub — no external lib, no network — so the 100%
coverage gate stays green. They pin: an exact match returns first/last word
timestamps; a repeated phrase is disambiguated by ``near_t``; ``align_fn=None`` and
missing phrases fail open to ``None``; and a degenerate span is rejected.
"""

import pytest

from fliphouse_worker.engine.align import align_phrase_to_words, phrase_boundaries


def _words(*triples):
    return [{"word": w, "start": s, "end": e} for (w, s, e) in triples]


WORDS = _words(
    ("итак", 0.0, 0.5),
    ("начнём", 0.6, 1.2),
    ("история", 5.0, 6.0),
    ("вот", 9.0, 9.3),
    ("и", 9.35, 9.5),
    ("всё", 9.6, 10.0),
)


def _exact_align_fn(spans):
    """Build an align_fn that maps a phrase → a fixed (i_start, i_end) span."""

    def align_fn(phrase, words, near_t):
        return spans.get(phrase)

    return align_fn


# ── align_phrase_to_words ────────────────────────────────────────────────────


def test_align_none_fn_returns_none_fail_open():
    assert align_phrase_to_words("итак начнём", WORDS, 0.0, align_fn=None) is None


def test_align_empty_phrase_returns_none():
    assert align_phrase_to_words("", WORDS, 0.0, align_fn=lambda p, w, t: (0, 1)) is None


def test_align_empty_words_returns_none():
    assert align_phrase_to_words("итак", (), 0.0, align_fn=lambda p, w, t: (0, 0)) is None


def test_align_delegates_to_injected_fn():
    fn = _exact_align_fn({"итак начнём": (0, 1)})
    assert align_phrase_to_words("итак начнём", WORDS, 0.0, align_fn=fn) == (0, 1)


def test_align_disambiguates_repeat_by_near_t():
    # A matcher that uses near_t to pick which of two occurrences to return.
    def align_fn(phrase, words, near_t):
        return (0, 1) if near_t < 4.0 else (3, 5)

    assert align_phrase_to_words("вот", WORDS, 0.0, align_fn=align_fn) == (0, 1)
    assert align_phrase_to_words("вот", WORDS, 9.0, align_fn=align_fn) == (3, 5)


# ── phrase_boundaries ────────────────────────────────────────────────────────


def test_phrase_boundaries_exact_match_returns_word_timestamps():
    h = {
        "start_time": 0.0,
        "end_time": 10.0,
        "start_phrase": "итак начнём",
        "end_phrase": "вот и всё",
    }
    fn = _exact_align_fn({"итак начнём": (0, 1), "вот и всё": (3, 5)})
    bounds = phrase_boundaries(h, WORDS, align_fn=fn)
    assert bounds == (pytest.approx(0.0), pytest.approx(10.0))  # words[0].start, words[5].end


def test_phrase_boundaries_none_when_align_fn_absent():
    h = {"start_time": 0.0, "end_time": 10.0, "start_phrase": "итак", "end_phrase": "всё"}
    assert phrase_boundaries(h, WORDS, align_fn=None) is None  # fail open to floats


def test_phrase_boundaries_none_when_phrases_missing():
    h = {"start_time": 0.0, "end_time": 10.0}  # no phrase keys
    assert phrase_boundaries(h, WORDS, align_fn=lambda p, w, t: (0, 1)) is None


def test_phrase_boundaries_none_when_one_phrase_blank():
    h = {"start_time": 0.0, "end_time": 10.0, "start_phrase": "итак", "end_phrase": ""}
    assert phrase_boundaries(h, WORDS, align_fn=lambda p, w, t: (0, 1)) is None


def test_phrase_boundaries_none_when_a_span_unresolved():
    h = {
        "start_time": 0.0,
        "end_time": 10.0,
        "start_phrase": "итак начнём",
        "end_phrase": "не найдётся",
    }
    fn = _exact_align_fn({"итак начнём": (0, 1)})  # end_phrase resolves to None
    assert phrase_boundaries(h, WORDS, align_fn=fn) is None


def test_phrase_boundaries_rejects_degenerate_span():
    # end word timestamp <= start word timestamp → out-of-order → fail open to None.
    h = {
        "start_time": 9.0,
        "end_time": 1.0,
        "start_phrase": "вот и всё",
        "end_phrase": "итак начнём",
    }
    fn = _exact_align_fn({"вот и всё": (3, 5), "итак начнём": (0, 1)})
    # i_start=3 (start 9.0), i_end=1 (end 1.2) → end_t < start_t → None.
    assert phrase_boundaries(h, WORDS, align_fn=fn) is None


def test_phrase_boundaries_tolerates_asr_drift_via_matcher():
    # The injected matcher absorbs ASR drift: the phrase text need not be byte-exact,
    # the stub still resolves it to the right word span.
    h = {
        "start_time": 0.0,
        "end_time": 6.0,
        "start_phrase": "итак нчнём",  # dropped vowel (ASR drift) — matcher tolerates
        "end_phrase": "история",
    }
    fn = _exact_align_fn({"итак нчнём": (0, 1), "история": (2, 2)})
    bounds = phrase_boundaries(h, WORDS, align_fn=fn)
    assert bounds == (pytest.approx(0.0), pytest.approx(6.0))  # words[0].start, words[2].end
