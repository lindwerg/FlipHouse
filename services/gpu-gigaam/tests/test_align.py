"""P3-A1 — CTC forced-alignment refine: pure realign core, fully fake-driven.

No torch/torchaudio/gigaam are imported here; the real ``_default_ctc_align`` body
is ``# pragma: no cover``. Every test exercises the PURE seam (``realign_payload`` +
``_realign_segment`` + ``_sanitize_spans`` + ``forced_align_enabled`` +
``resolve_align_fn``) by injecting fake aligners, so the contract — byte-identical
when OFF, fail-open per segment when ON, time-only — is proven without weights.
"""

from __future__ import annotations

from collections.abc import Callable

from fliphouse_gigaam.align import (
    ENV_FORCED_ALIGN,
    _default_ctc_align,
    _sanitize_spans,
    forced_align_enabled,
    realign_payload,
    resolve_align_fn,
)
from fliphouse_gigaam.contracts import RawPayload, Segment, Word


def _payload(*segments: Segment, duration: float = 5.0, language: str = "ru") -> RawPayload:
    return RawPayload(duration=duration, language=language, segments=tuple(segments))


def _seg(start: float, end: float, *words: Word, text: str = "т") -> Segment:
    return Segment(start=start, end=end, words=tuple(words), text=text)


def _two_word_payload() -> RawPayload:
    seg = _seg(
        0.0,
        2.0,
        Word(word="привет", start=0.0, end=1.0),
        Word(word="мир", start=1.0, end=2.0),
        text="Привет, мир.",
    )
    return _payload(seg, duration=2.0)


def _frozen_clock(value: float = 0.0) -> Callable[[], float]:
    return lambda: value


def _stepped_clock(values: list[float]) -> Callable[[], float]:
    """A clock that returns each value in turn, holding the last forever."""
    state = {"i": 0}

    def now() -> float:
        i = state["i"]
        if i < len(values) - 1:
            state["i"] = i + 1
        return values[i]

    return now


# ---------------- forced_align_enabled / resolve_align_fn ----------------


def test_enabled_truthy_spellings():
    for raw in ("1", "true", "TRUE", "Yes", " on "):
        assert forced_align_enabled({ENV_FORCED_ALIGN: raw}) is True


def test_disabled_falsy_or_missing():
    for env in ({}, {ENV_FORCED_ALIGN: ""}, {ENV_FORCED_ALIGN: "0"}, {ENV_FORCED_ALIGN: "off"}):
        assert forced_align_enabled(env) is False


def test_resolve_align_fn_disabled_is_none():
    assert resolve_align_fn({}) is None


def test_resolve_align_fn_enabled_returns_default_body():
    # Returns the (dormant) real aligner object WITHOUT invoking it (no weights).
    assert resolve_align_fn({ENV_FORCED_ALIGN: "1"}) is _default_ctc_align


# ---------------- byte-identical OFF default ----------------


def test_off_default_returns_same_object():
    payload = _two_word_payload()
    # The strongest byte-identical proof: the SAME object, no float churn.
    assert realign_payload(payload, "ignored.wav", align_fn=None) is payload


def test_off_default_never_touches_the_clock():
    payload = _two_word_payload()

    def boom() -> float:  # would raise if the OFF path consulted the clock
        raise AssertionError("clock must not be read on the disabled path")

    assert realign_payload(payload, "x.wav", align_fn=None, now_fn=boom) is payload


# ---------------- happy path (time-only refine) ----------------


def _shift_fn(delta: float):
    def align(_wav: str, seg: Segment):
        return [(w.start + delta, w.end + delta) for w in seg.words]

    return align


def test_happy_path_moves_only_word_times():
    payload = _two_word_payload()
    out = realign_payload(payload, "a.wav", align_fn=_shift_fn(0.1), now_fn=_frozen_clock())
    (seg,) = out.segments
    # cascade-relevant fields untouched.
    assert out.duration == payload.duration
    assert out.language == payload.language
    assert (seg.start, seg.end, seg.text) == (0.0, 2.0, "Привет, мир.")
    # word text + order + count untouched; only times moved.
    assert [w.word for w in seg.words] == ["привет", "мир"]
    assert seg.words[0].start == 0.1 and seg.words[0].end == 1.1
    # second word end (2.1) clamps to the segment window 2.0.
    assert seg.words[1].start == 1.1 and seg.words[1].end == 2.0


def test_cascade_fields_pristine_across_multi_segment():
    p = _payload(
        _seg(0.0, 1.0, Word("а", 0.0, 1.0), text="А."),
        _seg(1.0, 3.0, Word("бэ", 1.0, 2.0), Word("вэ", 2.0, 3.0), text="Бэ вэ."),
        duration=3.0,
    )
    out = realign_payload(p, "x.wav", align_fn=_shift_fn(0.05), now_fn=_frozen_clock())
    assert out.duration == 3.0 and out.language == "ru"
    for before, after in zip(p.segments, out.segments, strict=True):
        assert (after.start, after.end, after.text) == (before.start, before.end, before.text)
        assert [w.word for w in after.words] == [w.word for w in before.words]


def test_idempotent_on_stable_aligner():
    payload = _two_word_payload()
    once = realign_payload(payload, "x.wav", align_fn=_shift_fn(0.1), now_fn=_frozen_clock())
    twice = realign_payload(once, "x.wav", align_fn=_shift_fn(0.0), now_fn=_frozen_clock())
    assert [(w.start, w.end) for w in twice.segments[0].words] == [
        (w.start, w.end) for w in once.segments[0].words
    ]


# ---------------- fail-open per segment ----------------


def test_aligner_raises_keeps_rnnt_for_that_segment():
    def boom(_wav: str, _seg: Segment):
        raise RuntimeError("cuda go brr")

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=boom, now_fn=_frozen_clock())
    assert [(w.start, w.end) for w in out.segments[0].words] == [(0.0, 1.0), (1.0, 2.0)]


def test_per_segment_fail_open_isolated():
    # Segment 1 fails (returns None); 0 and 2 still align.
    def selective(_wav: str, seg: Segment):
        if seg.text == "skip":
            return None
        return [(w.start + 0.1, w.end + 0.1) for w in seg.words]

    p = _payload(
        _seg(0.0, 1.0, Word("а", 0.0, 0.5), text="ok0"),
        _seg(1.0, 2.0, Word("бэ", 1.0, 1.5), text="skip"),
        _seg(2.0, 3.0, Word("вэ", 2.0, 2.5), text="ok2"),
        duration=3.0,
    )
    out = realign_payload(p, "x.wav", align_fn=selective, now_fn=_frozen_clock())
    assert out.segments[0].words[0].start == 0.1
    assert out.segments[1].words[0].start == 1.0  # untouched RNN-T time
    assert out.segments[2].words[0].start == 2.1


def test_empty_words_segment_is_left_alone():
    called = {"n": 0}

    def align(_wav: str, seg: Segment):
        called["n"] += 1
        return []

    p = _payload(_seg(0.0, 1.0, text="silence"), duration=1.0)
    out = realign_payload(p, "x.wav", align_fn=align, now_fn=_frozen_clock())
    assert out.segments[0].words == ()
    assert called["n"] == 0  # the aligner is never even called for a wordless segment


# ---------------- _sanitize_spans guards ----------------


def test_span_count_mismatch_rejected():
    def wrong_count(_wav: str, seg: Segment):
        return [(0.0, 0.5)]  # 1 span for a 2-word segment

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=wrong_count, now_fn=_frozen_clock())
    assert [(w.start, w.end) for w in out.segments[0].words] == [(0.0, 1.0), (1.0, 2.0)]


def test_non_finite_span_rejected():
    def nan_span(_wav: str, seg: Segment):
        return [(0.0, float("inf")), (1.0, 2.0)]

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=nan_span, now_fn=_frozen_clock())
    assert [(w.start, w.end) for w in out.segments[0].words] == [(0.0, 1.0), (1.0, 2.0)]


def test_none_spans_rejected_directly():
    seg = _seg(0.0, 2.0, Word("а", 0.0, 1.0))
    assert _sanitize_spans(None, seg) is None


def test_window_clamp_pulls_spans_into_segment():
    def out_of_window(_wav: str, seg: Segment):
        return [(-5.0, 0.5), (1.5, 99.0)]

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=out_of_window, now_fn=_frozen_clock())
    spans = [(w.start, w.end) for w in out.segments[0].words]
    assert spans == [(0.0, 0.5), (1.5, 2.0)]  # clamped to [0.0, 2.0]


def test_inverted_span_end_lifted_to_start():
    def inverted(_wav: str, seg: Segment):
        return [(0.8, 0.3), (1.0, 2.0)]  # end < start on the first word

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=inverted, now_fn=_frozen_clock())
    w0 = out.segments[0].words[0]
    assert w0.start == 0.8 and w0.end == 0.8


def test_backwards_starts_forced_monotonic():
    def backwards(_wav: str, seg: Segment):
        return [(1.5, 1.8), (0.2, 0.6)]  # second start jumps back before the first

    payload = _two_word_payload()
    out = realign_payload(payload, "x.wav", align_fn=backwards, now_fn=_frozen_clock())
    starts = [w.start for w in out.segments[0].words]
    assert starts == [1.5, 1.5]  # second clamped up to the running max


# ---------------- wall-clock budget (fail-open partial progress) ----------------


def test_budget_exhausted_keeps_rnnt_for_remaining_segments():
    p = _payload(
        _seg(0.0, 1.0, Word("а", 0.0, 0.5), text="s0"),
        _seg(1.0, 2.0, Word("бэ", 1.0, 1.5), text="s1"),
        _seg(2.0, 3.0, Word("вэ", 2.0, 2.5), text="s2"),
        duration=3.0,
    )
    # deadline read = 0.0 -> deadline 10.0; seg0 check = 0.0 (aligns);
    # seg1 check = 99.0 (over budget) -> seg1 AND seg2 keep RNN-T.
    clock = _stepped_clock([0.0, 0.0, 99.0])
    out = realign_payload(p, "x.wav", align_fn=_shift_fn(0.1), now_fn=clock, budget_s=10.0)
    assert out.segments[0].words[0].start == 0.1  # aligned before the budget ran out
    assert out.segments[1].words[0].start == 1.0  # RNN-T preserved
    assert out.segments[2].words[0].start == 2.0  # RNN-T preserved
