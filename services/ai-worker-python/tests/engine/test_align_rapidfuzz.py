"""Unit coverage for engine/align_rapidfuzz.py — the REAL RapidFuzz align_fn.

Unlike test_align.py (which drives the PURE align module with a stub), these tests
exercise the concrete RapidFuzz (MIT) adapter end-to-end: token windowing, fuzzy
tolerance to ASR/LLM spelling drift, the ANCHOR_WINDOW_S repeated-phrase
disambiguator, and the MIN_MATCH_RATIO fail-closed gate. RapidFuzz is a real dep
(pyproject), so no branch is dodged — every line runs against the actual matcher.
"""

from fliphouse_worker.engine.align_rapidfuzz import (
    ANCHOR_WINDOW_S,
    MIN_MATCH_RATIO,
    _phrase_tokens,
    align_fn,
)


def _words(*triples):
    return [{"word": w, "start": s, "end": e} for (w, s, e) in triples]


WORDS = _words(
    ("Итак,", 0.0, 0.5),
    ("начнём", 0.6, 1.2),
    ("историю", 5.0, 6.0),
    ("вот", 9.0, 9.3),
    ("и", 9.35, 9.5),
    ("всё", 9.6, 10.0),
)


def test_phrase_tokens_normalizes_and_drops_empty():
    # Casing/punctuation stripped to bare tokens; an all-punct token (a lone hyphen,
    # which _norm strips to "") is dropped so it never widens the match window.
    assert _phrase_tokens("Итак, - начнём!") == ["итак", "начнём"]


def test_exact_match_returns_inclusive_span():
    # "итак начнём" → words[0..1]; near_t at the clip start.
    assert align_fn("итак начнём", WORDS, 0.0) == (0, 1)


def test_fuzzy_match_tolerates_asr_drift():
    # A dropped vowel ("нчнём") still resolves via RapidFuzz token ratio.
    assert align_fn("итак нчнём", WORDS, 0.0) == (0, 1)


def test_single_word_phrase_matches_one_index():
    assert align_fn("всё", WORDS, 10.0) == (5, 5)


def test_empty_phrase_returns_none():
    assert align_fn("   ", WORDS, 0.0) is None


def test_phrase_longer_than_words_returns_none():
    assert align_fn("один два три четыре пять шесть семь", WORDS, 0.0) is None


def test_no_confident_match_returns_none_fail_closed():
    # A phrase absent from the stream scores below MIN_MATCH_RATIO → None (fail-open).
    assert align_fn("абсолютно другое предложение здесь", WORDS, 5.0) is None


def test_anchor_window_excludes_far_occurrence():
    # "вот" at t≈9.0; with near_t far outside ANCHOR_WINDOW_S, no window qualifies.
    far_t = 9.0 + ANCHOR_WINDOW_S + 50.0
    assert align_fn("вот", WORDS, far_t) is None


def test_anchor_disambiguates_repeated_phrase_by_proximity():
    # "слово" repeats at t=0 and t=100; near_t picks the closer occurrence.
    words = _words(
        ("слово", 0.0, 0.4),
        ("дальше", 0.5, 1.0),
        ("слово", 100.0, 100.4),
        ("конец", 100.5, 101.0),
    )
    assert align_fn("слово", words, 0.0) == (0, 0)
    assert align_fn("слово", words, 100.0) == (2, 2)


def test_min_match_ratio_is_the_documented_gate():
    # Guards the constant the fail-closed branch depends on (regression sentinel).
    assert MIN_MATCH_RATIO == 80.0
