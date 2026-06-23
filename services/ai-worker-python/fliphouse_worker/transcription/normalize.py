"""Pure normalization: raw provider words → :class:`Transcript` (no I/O).

A provider emits a list of utterance segments, each carrying word timings, but
with raw-token quirks: a provider may prefix a token with a space, GigaAM-v3
emits clean Cyrillic tokens, and any of them can return a word/segment end a hair
past the media duration. This module flattens those quirks into the single
canonical contract:

* LEADING-SPACE invariant, applied IDEMPOTENTLY (``" " + word.lstrip()``) so a
  pre-spaced token stays single-spaced and a clean token gains exactly one space
  — re-normalizing is a no-op.
* end-times clamped to the effective duration; ``end >= start`` preserved.
* segment ``text`` derived FROM the (space-prefixed) words, so the cascade-
  consumed segment ALWAYS has a plain ``text`` key (consumers hard-subscript it).
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .provider import Segment, Transcript, Word, WordSegment


def leading_space(word: str) -> str:
    """Idempotent: exactly one leading space + the token (captacity convention)."""
    return " " + word.lstrip()


def _clamp(start: float, end: float, duration: float) -> tuple[float, float]:
    """Clamp ``start``/``end`` into ``[0, duration]`` and guarantee ``end >= start``.

    Non-finite inputs are sanitized (``inf``/``nan`` → the duration cap, else the
    floor), and a ``start`` past ``duration`` pins BOTH bounds to ``duration`` —
    a timing is never emitted past the media end, since consumers use
    ``segments[-1]["end"]`` as a duration proxy and any value must serialize to
    valid JSON (``Infinity`` is not).
    """
    cap = duration if duration > 0 else None
    lo = max(0.0, start) if math.isfinite(start) else 0.0
    hi = end if math.isfinite(end) else (cap if cap is not None else lo)
    if cap is not None:
        lo = min(lo, cap)
        hi = min(hi, cap)
    if hi < lo:
        hi = lo
    return lo, hi


def normalize_segments(
    raw_segments: Sequence[Mapping],
    *,
    duration: float,
    language: str,
    engine: str,
) -> Transcript:
    """Build a :class:`Transcript` from raw provider segments.

    ``raw_segments`` is a sequence of mappings ``{start, end, words:[{word,
    start, end}]}``. ``duration`` is authoritative when positive; otherwise it is
    inferred from the latest word/segment end (so a provider that omits duration
    still produces a sane bound).
    """
    raw = list(raw_segments)

    inferred_end = 0.0
    for rs in raw:
        for value in (rs.get("end", 0.0), *(rw.get("end", 0.0) for rw in rs.get("words", ()))):
            v = float(value)
            if math.isfinite(v):  # a non-finite provider end must never set the bound
                inferred_end = max(inferred_end, v)
    eff_duration = float(duration) if duration and duration > 0 else inferred_end
    if not math.isfinite(eff_duration):  # unknown duration; clamping disabled beats inf
        eff_duration = 0.0

    segments: list[Segment] = []
    word_segments: list[WordSegment] = []
    for rs in raw:
        words: list[Word] = []
        for rw in rs.get("words", ()):
            ws, we = _clamp(float(rw["start"]), float(rw["end"]), eff_duration)
            words.append(Word(word=leading_space(str(rw["word"])), start=ws, end=we))

        seg_start = float(rs["start"]) if "start" in rs else (words[0].start if words else 0.0)
        seg_end = float(rs["end"]) if "end" in rs else (words[-1].end if words else 0.0)
        ss, se = _clamp(seg_start, seg_end, eff_duration)

        # collapse any internal double-spaces (a trailing-spaced raw token would
        # otherwise yield "a  b") while keeping single word separation.
        text = " ".join("".join(w.word for w in words).split())
        segments.append(Segment(start=ss, end=se, text=text))
        word_segments.append(WordSegment(start=ss, end=se, words=tuple(words)))

    return Transcript(
        duration=eff_duration,
        language=language,
        engine=engine,
        segments=tuple(segments),
        word_segments=tuple(word_segments),
    )
