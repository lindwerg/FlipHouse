"""Pure normalization contract tests — leading-space, clamping, text derivation."""

from __future__ import annotations

from fliphouse_worker.transcription import leading_space, normalize_segments
from fliphouse_worker.transcription.normalize import _clamp


def test_leading_space_prefixes_clean_token():
    # GigaAM/wav2vec2 emit clean Cyrillic tokens — gain exactly one leading space.
    assert leading_space("Привет") == " Привет"


def test_leading_space_is_idempotent_on_already_spaced_token():
    # Whisper already prefixes a space — must stay SINGLE-spaced (no double space).
    assert leading_space(" Привет") == " Привет"
    assert leading_space(leading_space("Привет")) == " Привет"


def test_leading_space_collapses_multiple_leading_spaces():
    assert leading_space("   word") == " word"


def test_normalize_prefixes_leading_space_for_both_provider_shapes():
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "words": [
                {"word": "Привет", "start": 0.0, "end": 0.5},  # clean (GigaAM)
                {"word": " мир", "start": 0.5, "end": 1.0},  # already spaced (Whisper)
            ],
        }
    ]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="x")
    words = t.word_segments[0].words
    assert [w.word for w in words] == [" Привет", " мир"]
    # segment text is derived FROM the space-prefixed words, then stripped.
    assert t.segments[0].text == "Привет мир"


def test_normalize_clamps_word_and_segment_end_to_duration():
    raw = [
        {
            "start": 0.0,
            "end": 9.0,
            "words": [
                {"word": "a", "start": 0.0, "end": 9.0},  # end past the 2s media
            ],
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="x")
    assert t.duration == 2.0
    assert t.word_segments[0].words[0].end == 2.0
    assert t.segments[0].end == 2.0


def test_normalize_infers_duration_when_not_given():
    raw = [{"start": 0.0, "end": 3.5, "words": [{"word": "a", "start": 0.0, "end": 3.5}]}]
    t = normalize_segments(raw, duration=0.0, language="ru", engine="x")
    assert t.duration == 3.5


def test_normalize_derives_segment_bounds_from_words_when_missing():
    # cloud/whisper segment lacking explicit start/end → derive from first/last word.
    raw = [
        {
            "words": [
                {"word": "a", "start": 1.0, "end": 1.5},
                {"word": "b", "start": 1.5, "end": 2.0},
            ]
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="x")
    assert t.segments[0].start == 1.0
    assert t.segments[0].end == 2.0


def test_normalize_segment_without_words_or_bounds_is_zeroed():
    raw = [{"words": []}]
    t = normalize_segments(raw, duration=0.0, language="ru", engine="x")
    assert t.segments[0].start == 0.0
    assert t.segments[0].end == 0.0
    assert t.segments[0].text == ""
    assert t.word_segments[0].words == ()


def test_normalize_empty_segments_yields_empty_contract():
    t = normalize_segments([], duration=0.0, language="ru", engine="x")
    assert t.segments == ()
    assert t.word_segments == ()
    assert t.duration == 0.0
    # the cascade-consumed projection is an empty list, not a crash.
    assert t.to_cascade_dict()["segments"] == []


def test_normalize_preserves_word_order():
    raw = [
        {
            "start": 0.0,
            "end": 3.0,
            "words": [
                {"word": "one", "start": 0.0, "end": 1.0},
                {"word": "two", "start": 1.0, "end": 2.0},
                {"word": "three", "start": 2.0, "end": 3.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=3.0, language="ru", engine="x")
    assert [w.word for w in t.word_segments[0].words] == [" one", " two", " three"]


def test_clamp_branches():
    # duration<=0 → end passes through; end<start → end snapped up to start.
    assert _clamp(0.0, 1.0, 0.0) == (0.0, 1.0)
    assert _clamp(5.0, 3.0, 10.0) == (5.0, 5.0)
    assert _clamp(-1.0, 2.0, 10.0) == (0.0, 2.0)  # negative start floored to 0
    # start past duration → BOTH bounds pinned to duration (never past media end).
    assert _clamp(15.0, 20.0, 10.0) == (10.0, 10.0)


def test_clamp_sanitizes_non_finite():
    # inf/nan end → capped to duration (or floor when duration unknown).
    assert _clamp(0.0, float("inf"), 10.0) == (0.0, 10.0)
    assert _clamp(1.0, float("inf"), 0.0) == (1.0, 1.0)
    assert _clamp(float("nan"), 2.0, 10.0) == (0.0, 2.0)


def test_normalize_non_finite_end_does_not_poison_duration():
    # A provider returning inf must not propagate to duration (invalid JSON) when
    # no explicit duration is given.
    raw = [
        {
            "start": 0.0,
            "end": float("inf"),
            "words": [
                {"word": "x", "start": 0.0, "end": float("inf")},
            ],
        }
    ]
    t = normalize_segments(raw, duration=0.0, language="ru", engine="x")
    assert t.duration == 0.0
    assert t.word_segments[0].words[0].end == 0.0  # inf sanitized to the floor


def test_normalize_explicit_inf_duration_is_sanitized():
    # An explicitly-passed non-finite duration must not land in the contract.
    raw = [{"start": 0.0, "end": 1.0, "words": [{"word": "x", "start": 0.0, "end": 1.0}]}]
    t = normalize_segments(raw, duration=float("inf"), language="ru", engine="x")
    assert t.duration == 0.0


def test_normalize_collapses_trailing_space_tokens():
    # A trailing-spaced raw token must not create a double internal space in text.
    raw = [
        {
            "start": 0.0,
            "end": 2.0,
            "words": [
                {"word": "hello ", "start": 0.0, "end": 1.0},
                {"word": "world", "start": 1.0, "end": 2.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="x")
    assert t.segments[0].text == "hello world"


# ── TRANS-1: provider punctuated segment text → cascade text + sentence-end projection ──


def test_normalize_prefers_provider_segment_text_over_word_join():
    # GigaAM v3 emits punctuated/normalized segment text; it must WIN over the bare
    # word join so the LLM scorer sees punctuation/casing.
    raw = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Привет, мир!",
            "words": [
                {"word": "привет", "start": 0.0, "end": 1.0},
                {"word": "мир", "start": 1.0, "end": 2.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="gigaam-v3")
    assert t.segments[0].text == "Привет, мир!"  # provider text preserved verbatim
    assert t.to_cascade_dict()["segments"][0]["text"] == "Привет, мир!"


def _ends_terminal(word: str) -> bool:
    """Local mirror of engine ``ends_with_terminal_punct`` (avoids importing the
    engine package, which transitively pulls in rapidfuzz that the normalize gate
    does not depend on). The engine side has its OWN test for the same set."""
    return word.strip().rstrip("\"'`)]}»”’").endswith((".", "!", "?", "…"))


def test_normalize_projects_sentence_end_onto_last_word():
    # A segment whose provider text ends with '…мысль.' must yield a LAST word the
    # snapper can read as a sentence end via terminal punctuation.
    raw = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "Это законченная мысль.",
            "words": [
                {"word": "это", "start": 0.0, "end": 0.5},
                {"word": "законченная", "start": 0.5, "end": 1.2},
                {"word": "мысль", "start": 1.2, "end": 2.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="gigaam-v3")
    last = t.word_segments[0].words[-1]
    assert last.word.endswith(".")
    assert _ends_terminal(last.word) is True


def test_normalize_does_not_project_when_segment_text_not_terminal():
    # A non-terminal segment text (mid-thought) must NOT fabricate a sentence end.
    raw = [
        {
            "start": 0.0,
            "end": 2.0,
            "text": "это только начало",
            "words": [
                {"word": "это", "start": 0.0, "end": 1.0},
                {"word": "начало", "start": 1.0, "end": 2.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=2.0, language="ru", engine="gigaam-v3")
    assert not t.word_segments[0].words[-1].word.endswith((".", "!", "?", "…"))


def test_normalize_projection_idempotent_when_last_word_already_terminal():
    # If the bare last token somehow already carries '.', do not double it.
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Готово.",
            "words": [{"word": "готово.", "start": 0.0, "end": 1.0}],
        }
    ]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")
    assert t.word_segments[0].words[-1].word.rstrip().endswith(".")
    assert not t.word_segments[0].words[-1].word.endswith("..")


def test_normalize_projection_honors_closing_quote_before_terminal():
    # Terminal punctuation behind a closing quote still marks a sentence end.
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "Он сказал «да».",
            "words": [
                {"word": "он", "start": 0.0, "end": 0.3},
                {"word": "сказал", "start": 0.3, "end": 0.6},
                {"word": "да", "start": 0.6, "end": 1.0},
            ],
        }
    ]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")
    assert _ends_terminal(t.word_segments[0].words[-1].word) is True


def test_normalize_falls_back_to_word_join_when_provider_text_absent():
    # No provider text → legacy behavior (derive from words), no projection.
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "words": [{"word": "слово", "start": 0.0, "end": 1.0}],
        }
    ]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")
    assert t.segments[0].text == "слово"
    assert t.word_segments[0].words[-1].word == " слово"


def test_normalize_empty_provider_text_uses_word_join():
    # An explicit empty-string text falls back to the word join (no projection).
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "text": "   ",
            "words": [{"word": "слово", "start": 0.0, "end": 1.0}],
        }
    ]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")
    assert t.segments[0].text == "слово"


def test_normalize_terminal_provider_text_with_no_words_is_safe():
    # A terminal segment text with NO words must not crash the projection (it has
    # no last word to mark); the cascade text still wins.
    raw = [{"start": 0.0, "end": 1.0, "text": "Тишина.", "words": []}]
    t = normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")
    assert t.segments[0].text == "Тишина."
    assert t.word_segments[0].words == ()
