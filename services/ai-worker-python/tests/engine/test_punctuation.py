"""Unit coverage for engine/punctuation.py — RU sentence-boundary restoration.

RU ASR (GigaAM-v3) rarely emits terminal punctuation, so these tests pin the
HEURISTIC restorer: it must flag a sentence end from a structural pause + a
fresh-start cue, honor terminal punctuation when present, recognize RU STOP
discourse markers, and stay CONSERVATIVE (a bare pause with no fresh-start cue is
just a breath, not a sentence end). Discourse START detection is pinned too.
"""

from fliphouse_worker.engine.punctuation import (
    LONG_PAUSE_S,
    SENT_PAUSE_S,
    annotate_sentence_ends,
    ends_discourse,
    ends_with_terminal_punct,
    starts_discourse,
)


def _w(word, start, end):
    return {"word": word, "start": start, "end": end}


# ── terminal punctuation ─────────────────────────────────────────────────────


def test_terminal_punct_plain_and_ru_quote():
    assert ends_with_terminal_punct("готово.")
    assert ends_with_terminal_punct("он?»")  # RU closing quote stripped first
    assert not ends_with_terminal_punct("слово")


def test_punctuated_word_is_flagged_regardless_of_pause():
    words = [_w("готово.", 0.0, 1.0), _w("дальше", 1.05, 2.0)]  # tiny gap
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is True  # punctuation wins even without a pause
    assert out[1]["sent_end"] is False


# ── pause + fresh-start heuristic ────────────────────────────────────────────


def test_pause_plus_capitalized_next_flags_sentence_end():
    words = [_w("закончил", 0.0, 1.0), _w("Потом", 1.6, 2.0)]  # gap 0.6 >= 0.45, next Capitalized
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is True


def test_pause_plus_discourse_opener_flags_sentence_end():
    words = [_w("закончил", 0.0, 1.0), _w("итак", 1.6, 2.0)]  # discourse START opener after a pause
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is True


def test_bare_pause_without_fresh_start_is_not_flagged():
    words = [_w("слово", 0.0, 1.0), _w("ещё", 1.6, 2.0)]  # pause but next is lowercase, no marker
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is False  # conservative: a breath is not a sentence end


def test_short_gap_does_not_flag_even_with_capitalized_next():
    words = [_w("слово", 0.0, 1.0), _w("Имя", 1.2, 2.0)]  # gap 0.2 < SENT_PAUSE_S
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is False


def test_pause_with_non_alphabetic_next_token_is_not_flagged():
    # Next token after the pause has no alphabetic char (a number) → not a capital
    # start cue and no discourse marker → conservative, NOT a sentence end.
    words = [_w("осталось", 0.0, 1.0), _w("100", 1.6, 2.0)]  # gap 0.6 >= SENT_PAUSE_S
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is False


# ── LONG-pause rule (sentence end on its own, no fresh-start cue) ────────────


def test_long_pause_alone_flags_sentence_end_without_any_cue():
    # GigaAM monologue: no punctuation, no capital, no discourse marker — but a
    # 0.7s+ silence is a real stop, so the PRIOR word is a sentence end on its own.
    words = [_w("закончил", 0.0, 1.0), _w("ещё", 1.75, 2.5)]  # gap 0.75 >= LONG_PAUSE_S
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is True  # long silence alone completes the thought


def test_long_pause_threshold_is_inclusive():
    words = [_w("слово", 0.0, 1.0), _w("дальше", 1.0 + LONG_PAUSE_S, 2.5)]  # gap == LONG_PAUSE_S
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is True


def test_medium_pause_below_long_still_needs_fresh_start_cue():
    # Gap in [SENT_PAUSE_S, LONG_PAUSE_S): lowercase, no marker → NOT a sentence end
    # (the long-pause shortcut must not fire here; the medium rule stays conservative).
    gap = (SENT_PAUSE_S + LONG_PAUSE_S) / 2  # strictly between the two thresholds
    words = [_w("слово", 0.0, 1.0), _w("ещё", 1.0 + gap, 2.5)]
    out = annotate_sentence_ends(words)
    assert out[0]["sent_end"] is False


# ── STOP discourse markers ───────────────────────────────────────────────────


def test_stop_marker_multiword_flags_its_last_word():
    words = [_w("вот", 0.0, 0.3), _w("и", 0.35, 0.5), _w("всё", 0.55, 0.9)]
    out = annotate_sentence_ends(words)
    assert out[-1]["sent_end"] is True  # "вот и всё" wraps the thought up


def test_stop_marker_yo_dropped_variant():
    words = [_w("вот", 0.0, 0.3), _w("и", 0.35, 0.5), _w("все", 0.55, 0.9)]  # ASR drops ё
    out = annotate_sentence_ends(words)
    assert out[-1]["sent_end"] is True


# ── discourse marker predicates ──────────────────────────────────────────────


def test_starts_discourse_single_and_multiword():
    assert starts_discourse(["итак", "поехали"], 0)
    assert starts_discourse(["так", "вот", "история"], 0)  # multi-word "так вот"
    assert not starts_discourse(["просто", "слово"], 0)


def test_ends_discourse_matches_v_itoge():
    assert ends_discourse(["в", "итоге", "всё"], 0)
    assert not ends_discourse(["в", "процессе"], 0)


def test_empty_word_list_returns_empty():
    assert annotate_sentence_ends([]) == []


def test_annotate_is_pure_does_not_mutate_input():
    words = [_w("готово.", 0.0, 1.0)]
    annotate_sentence_ends(words)
    assert "sent_end" not in words[0]  # input untouched


# ── punct_fn seam (injectable RU punctuation-restoration model) ──────────────


def test_punct_fn_none_reproduces_pause_heuristic_exactly():
    # REGRESSION PIN: with no model the output is byte-for-byte today's flags.
    words = [
        _w("закончил", 0.0, 1.0),
        _w("ещё", 1.75, 2.5),  # LONG pause → out[0] sent_end
        _w("слово", 2.6, 3.0),  # no following pause → out[1] False
    ]
    baseline = annotate_sentence_ends(words)
    seamed = annotate_sentence_ends(words, punct_fn=None)
    assert [w["sent_end"] for w in baseline] == [w["sent_end"] for w in seamed]
    assert [w["sent_end"] for w in baseline] == [True, False, False]


def test_punct_fn_flag_forces_sentence_end_with_no_pause():
    # GigaAM monologue with NO pause anywhere; the model alone marks word i a
    # terminus → sent_end[i] must be True even though the pause heuristic is silent.
    words = [_w("первое", 0.0, 1.0), _w("второе", 1.05, 2.0)]  # tiny gap, no cue

    def punct_fn(ws):
        return [True, False]  # model says word 0 ends a sentence

    out = annotate_sentence_ends(words, punct_fn=punct_fn)
    assert out[0]["sent_end"] is True  # model overrides a silent pause heuristic
    assert out[1]["sent_end"] is False


def test_punct_fn_flag_overrides_noisy_long_pause_disagreement():
    # The pause heuristic would flag word 0 (LONG pause), but the model says NO
    # boundary there and YES at word 1 (mid-pause). The model takes precedence on
    # the words it flags; word 0 still gets the pause fallback (model left it False).
    words = [
        _w("слово", 0.0, 1.0),
        _w("дальше", 1.8, 2.5),  # LONG pause after word 0
        _w("конец", 2.55, 3.0),
    ]

    def punct_fn(ws):
        return [False, True, False]  # model flags word 1, not word 0

    out = annotate_sentence_ends(words, punct_fn=punct_fn)
    assert out[1]["sent_end"] is True  # model-confirmed terminus, no pause needed
    # word 0: model left False, so the LONG-pause fallback still flags it.
    assert out[0]["sent_end"] is True


def test_punct_fn_length_mismatch_is_ignored_fail_open():
    # A buggy adapter returns the wrong number of flags → IGNORED; the result equals
    # the pure pause-heuristic output (never corrupts the boundary set).
    words = [_w("закончил", 0.0, 1.0), _w("ещё", 1.75, 2.5)]  # LONG pause → word 0 True

    def bad_punct_fn(ws):
        return [True]  # length 1 != 2 words → dropped

    out = annotate_sentence_ends(words, punct_fn=bad_punct_fn)
    baseline = annotate_sentence_ends(words)
    assert [w["sent_end"] for w in out] == [w["sent_end"] for w in baseline]


def test_punct_fn_truthy_values_are_coerced_to_bool():
    # The model mask may carry truthy/falsey non-bools; they are coerced cleanly.
    words = [_w("a", 0.0, 1.0), _w("b", 1.05, 2.0)]

    def punct_fn(ws):
        return [1, 0]  # truthy / falsey ints

    out = annotate_sentence_ends(words, punct_fn=punct_fn)
    assert out[0]["sent_end"] is True
    assert out[1]["sent_end"] is False
