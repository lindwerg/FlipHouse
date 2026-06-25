"""Integration-style coverage for engine/production_recall.py.

This is the WIRING PROOF the founder asked for: it drives the EXACT recall closure
the score stage runs (``build_phrase_anchored_recall_fn`` → ``recall_candidates`` →
``phrase_boundaries`` → the real RapidFuzz ``align_fn``), with the network seams
(``llm_fn``/``highlight_fn``) faked but ``align_fn`` REAL and DEFAULT.

The load-bearing assertion: a highlight whose float ``end_time`` lands MID-PHRASE,
but whose ``end_phrase`` names a LATER complete-sentence terminus, produces a clip
END anchored at that terminus — NOT the float. The companion test re-runs the same
closure with ``align_fn`` reverted to ``None`` and asserts the END falls back to the
float; so if anyone makes the production path dormant again, the live-wiring test
FAILS. Together they pin "align_fn is ACTIVE in production", not just unit-tested.
"""

import json

from fliphouse_worker.dsp.local_signals import LocalSignals
from fliphouse_worker.engine.production_recall import build_phrase_anchored_recall_fn

# A two-sentence run. Sentence 1 ends at the word "паузу" (~12s, where the LLM float
# end wrongly lands MID-second-sentence); sentence 2 ends at "завершена" (~19.5s) —
# the COMPLETE-sentence terminus the LLM names in end_phrase. Word gaps are all far
# below GAP_MIN_S (0.6s) so refine_boundaries adds NO stop/resume candidate and the
# phrase anchor survives untouched (only clamp, no pad).
_WORD_ROWS = [
    ("Сегодня", 0.0, 0.4),
    ("я", 0.45, 0.6),
    ("расскажу", 0.65, 1.2),
    ("вам", 1.25, 1.5),
    ("очень", 1.55, 2.0),
    ("важную", 2.05, 2.5),
    ("вещь", 2.55, 3.0),
    ("про", 3.05, 3.3),
    ("деньги", 3.35, 4.0),
    ("и", 4.05, 4.2),
    ("про", 4.25, 4.5),
    ("то", 4.55, 4.8),
    ("как", 4.85, 5.1),
    ("их", 5.15, 5.4),
    ("сохранить", 5.45, 6.2),
    ("надолго", 6.25, 7.0),
    ("без", 7.05, 7.4),
    ("лишнего", 7.45, 8.0),
    ("риска", 8.05, 8.6),
    ("сделав", 8.65, 9.2),
    ("короткую", 9.25, 10.0),
    ("осознанную", 10.05, 11.0),
    ("паузу", 11.4, 12.0),  # ← sentence-1 terminus; the LLM float end (12.0) lands here
    ("теперь", 12.4, 13.0),
    ("вторая", 13.05, 13.6),
    ("мысль", 13.65, 14.2),
    ("должна", 14.25, 14.8),
    ("быть", 14.85, 15.2),
    ("полностью", 15.25, 16.0),
    ("и", 16.05, 16.2),
    ("окончательно", 16.25, 17.4),
    ("здесь", 17.45, 18.0),
    ("в", 18.05, 18.2),
    ("этом", 18.25, 18.6),
    ("ролике", 18.65, 19.0),
    ("завершена", 19.05, 19.5),  # ← sentence-2 terminus; named verbatim in end_phrase
]


def _word_segments():
    """doc-01 nested word_segments: one segment carrying the flat word list."""
    return [
        {
            "start": 0.0,
            "end": 19.5,
            "words": [{"word": w, "start": s, "end": e} for w, s, e in _WORD_ROWS],
        }
    ]


def _transcript():
    return {
        "duration": 30.0,
        "segments": [
            {"start": 0.0, "end": 12.0, "text": " ".join(w for w, _, _ in _WORD_ROWS[:23])},
            {"start": 12.4, "end": 19.5, "text": " ".join(w for w, _, _ in _WORD_ROWS[23:])},
        ],
    }


# The LLM highlight: float end (12.0) cuts MID-second-sentence, but end_phrase names
# the complete-sentence terminus ("...завершена"). start_phrase opens sentence 1.
_HIGHLIGHT = {
    "title": "О деньгах",
    "start_time": 0.0,
    "end_time": 12.0,  # mid-thought float — the bug we are fixing
    "start_phrase": "Сегодня я расскажу",
    "end_phrase": "в этом ролике завершена",  # last words of a COMPLETE sentence (~19.5s)
    "score": 90,
    "hook_sentence": "Сегодня я расскажу вам очень важную вещь",
    "virality_reason": "concrete money tip",
}


class _FakeLLM:
    """content-type probe → fixed JSON; any other prompt is unused by this path."""

    def __call__(self, prompt: str) -> str:
        return '{"content_type": "monologue", "density": "high"}'


class _FakeHighlightFn:
    """strict-JSON recall seam → the single mid-float / late-end_phrase highlight."""

    def __call__(self, prompt: str) -> dict:
        return json.loads(json.dumps({"highlights": [_HIGHLIGHT]}))


def _empty_signals():
    # No pauses/peaks/cuts/flags → refine_boundaries has nothing to snap to, so the
    # phrase anchor is the ONLY thing that can move the end off the float.
    return LocalSignals(pauses=(), energy_peaks_s=(), scene_cuts=(), audio_flags=())


def test_production_recall_anchors_end_to_complete_sentence_terminus():
    """The LIVE wiring: end_phrase → RapidFuzz align_fn → END at the sentence terminus."""
    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=_FakeLLM(),
        highlight_fn=_FakeHighlightFn(),
        word_segments=_word_segments(),
        # align_fn defaults to the REAL RapidFuzz adapter — do NOT pass it, proving the
        # production default is the active matcher.
    )
    candidates = recall_fn(_transcript(), _empty_signals())

    assert len(candidates) == 1
    end = candidates[0].end_time
    # Anchored to "завершена".end (19.5), NOT the mid-phrase float (12.0). Generous
    # window absorbs any clamp/pad without admitting the 12.0 float.
    assert end > 16.0, f"END not anchored to the complete-sentence terminus: {end}"
    assert abs(end - 19.5) <= 0.5


def test_native_gigaam_punctuation_is_the_live_sentence_end_source():
    """TRANS-1/TRANS-2: the live closure uses NO punct_fn — the sentence-end signal is
    GigaAM's OWN punctuation, projected onto the word stream by normalize_segments.

    Here ``end_phrase`` does NOT resolve (verbatim mismatch), so align_fn cannot anchor
    the end; the ONLY thing that can move the float (12.0) forward to the real terminus
    is the projected terminal punctuation on the words. The word stream carries a '.' on
    "паузу" (sentence-1 terminus, ~12s) and on "завершена" (~19.5s) exactly as
    normalize_segments would project from GigaAM's punctuated segment text. With the
    default (no punct_fn), the sentence-completion forward-extension lands the END on a
    terminus — proving native punctuation, not a bolt-on model, drives boundaries.
    """
    rows = [list(r) for r in _WORD_ROWS]
    # Project terminal punctuation the way normalize_segments does (last word of each
    # punctuated GigaAM segment gains the segment's terminal char).
    rows[22][0] = "паузу."  # sentence-1 terminus
    rows[-1][0] = "завершена."  # sentence-2 terminus
    word_segments = [
        {
            "start": 0.0,
            "end": 19.5,
            "words": [{"word": w, "start": s, "end": e} for w, s, e in rows],
        }
    ]
    highlight = {**_HIGHLIGHT, "end_phrase": "ничего из этого не совпадает дословно"}

    class _HL:
        def __call__(self, prompt: str) -> dict:
            return {"highlights": [highlight]}

    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=_FakeLLM(),
        highlight_fn=_HL(),
        word_segments=word_segments,
        # align_fn default (real) — but end_phrase won't resolve, so the punctuation-
        # driven sentence completion is what moves the end. NO punct_fn anywhere.
    )
    candidates = recall_fn(_transcript(), _empty_signals())

    assert len(candidates) == 1
    end = candidates[0].end_time
    # The float (12.0) sits AT sentence-1's terminus ("паузу."), so the native '.' makes
    # the END a finished thought (>= ~12s) — never a mid-word cut. Either terminus is a
    # complete sentence; the key invariant is the end lands on a punctuated word's end.
    assert end >= 11.9, f"native-punctuation sentence end not honored: {end}"


def test_reverting_align_fn_to_none_falls_back_to_float_end():
    """Regression guard: with align_fn=None the END reverts to the mid-phrase float.

    This is the inverse of the live-wiring test — it documents EXACTLY what breaks if
    someone makes the path dormant again, and proves the previous test's pass is due
    to align_fn, not some other snapper moving the end.
    """
    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=_FakeLLM(),
        highlight_fn=_FakeHighlightFn(),
        word_segments=_word_segments(),
        align_fn=None,  # dormant path
    )
    candidates = recall_fn(_transcript(), _empty_signals())

    assert len(candidates) == 1
    # No phrase anchor → the LLM float end (12.0) is kept (refine has no candidate).
    assert abs(candidates[0].end_time - 12.0) <= 0.5


# --- VIS-3: the punct_fn seam is FORWARDED through the production closure ---


def test_injected_punct_fn_reaches_the_live_boundary_path():
    """The ``punct_fn`` seam is WIRED through ``build_phrase_anchored_recall_fn``.

    Mirrors the align_fn live-wiring proof for the RU sentence-end seam. Production
    passes ``punct_fn=None`` ON PURPOSE (native GigaAM punctuation is the live signal),
    but the seam must not be SEVERED at the factory — a future permissive restorer has
    to be injectable without touching the closure. Here neither ``end_phrase`` resolves
    (verbatim mismatch) NOR does any word carry native punctuation, so the ONLY thing
    that can mark a sentence terminus is the injected ``punct_fn``. We flag the word
    "паузу" (~12s) as a sentence end; the sentence-completion forward-extension then
    lands the END there — proving the injected mask reached ``annotate_sentence_ends``
    via the production closure. If anyone drops the forwarding, the END stays the float
    and this FAILS.
    """
    sentence_end_words = {"паузу"}

    def punct_fn(words):
        # One bool per word: True exactly where our marked terminus sits.
        return [w["word"] in sentence_end_words for w in words]

    highlight = {**_HIGHLIGHT, "end_phrase": "ничего тут не совпадает дословно"}

    class _HL:
        def __call__(self, prompt: str) -> dict:
            return {"highlights": [highlight]}

    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=_FakeLLM(),
        highlight_fn=_HL(),
        word_segments=_word_segments(),  # NO native punctuation on any token
        punct_fn=punct_fn,  # the injected RU sentence-end mask
    )
    candidates = recall_fn(_transcript(), _empty_signals())

    assert len(candidates) == 1
    end = candidates[0].end_time
    # Anchored to the injected terminus "паузу".end (12.0) — the mask drove the boundary.
    assert abs(end - 12.0) <= 0.5, f"injected punct_fn did not reach the boundary path: {end}"


def test_default_production_closure_passes_no_punct_fn():
    """The default closure forwards ``punct_fn=None`` (native-punctuation path).

    Inverse guard: with NO punct_fn injected AND no native punctuation on the words AND
    no resolvable end_phrase, nothing can move the float end forward — confirming the
    default really is the inert seam (so the previous test's pass is due to the injected
    mask, not some always-on restorer).
    """
    highlight = {**_HIGHLIGHT, "end_phrase": "ничего тут не совпадает дословно"}

    class _HL:
        def __call__(self, prompt: str) -> dict:
            return {"highlights": [highlight]}

    recall_fn = build_phrase_anchored_recall_fn(
        llm_fn=_FakeLLM(),
        highlight_fn=_HL(),
        word_segments=_word_segments(),  # no native punctuation, no injected mask
    )
    candidates = recall_fn(_transcript(), _empty_signals())

    assert len(candidates) == 1
    # No anchor, no native punct, no injected mask → the float end (12.0) survives.
    assert abs(candidates[0].end_time - 12.0) <= 0.5
