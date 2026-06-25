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
* segment ``text`` PREFERS the provider's punctuated/normalized ``text`` (GigaAM
  v3 ``e2e_rnnt`` emits punctuation/casing at the SEGMENT level, never on bare
  per-word tokens — TRANS-1), falling back to the join of the space-prefixed words
  when the provider omits it. Either way the cascade-consumed segment ALWAYS has a
  plain ``text`` key (consumers hard-subscript it).
* SENTENCE-END PROJECTION (TRANS-1): when the provider's segment ``text`` ends on
  terminal punctuation (``.``/``!``/``?``/``…``), the segment's LAST word inherits
  that punctuation in the ``word_segments`` stream. The bare GigaAM tokens carry no
  punctuation, so without this projection the boundary snapper's only sentence-end
  signal is the pause heuristic; projecting the real terminal mark gives
  ``ends_with_terminal_punct`` (and thus ``_ends_sentence``) a TRUE native signal at
  every model-detected sentence boundary.
"""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence

from .provider import Segment, Transcript, Word, WordSegment

# Terminal sentence punctuation + the closing quotes/brackets that may trail it.
# Kept LOCAL to the transcription package (not imported from the engine) so the
# normalize boundary stays decoupled from the scoring engine; ``engine/punctuation``
# owns the identical set for the snapper side.
_SENTENCE_END_CHARS = (".", "!", "?", "…")
_TRAILING_STRIP = "\"'`)]}»”’"


def leading_space(word: str) -> str:
    """Idempotent: exactly one leading space + the token (captacity convention)."""
    return " " + word.lstrip()


def _segment_text_ends_sentence(text: str) -> bool:
    """True when provider segment text ends on terminal punctuation (TRANS-1 signal).

    Closing quotes/brackets are stripped first so ``…мысль."`` still counts.
    """
    return text.strip().rstrip(_TRAILING_STRIP).endswith(_SENTENCE_END_CHARS)


def _project_sentence_end(words: list[Word], terminal: str) -> list[Word]:
    """Return ``words`` with the terminal char appended to the LAST word.

    PURE: builds a new list with a new final :class:`Word` (immutability). When the
    provider segment text ends a sentence but the bare last token carries no
    punctuation, this re-attaches the terminal mark so the downstream
    ``ends_with_terminal_punct`` snapper sees a native sentence end. A last token
    that ALREADY ends on terminal punctuation is left untouched (idempotent)."""
    if not words:
        return words
    last = words[-1]
    if last.word.rstrip().rstrip(_TRAILING_STRIP).endswith(_SENTENCE_END_CHARS):
        return words
    return [*words[:-1], Word(word=last.word + terminal, start=last.start, end=last.end)]


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

        # PREFER the provider's punctuated/normalized segment text (GigaAM v3 emits
        # punctuation here); else rebuild from the words. Collapse any internal
        # double-spaces (a trailing-spaced raw token would otherwise yield "a  b").
        provider_text = str(rs.get("text", "")).strip()
        text = provider_text or " ".join("".join(w.word for w in words).split())

        # SENTENCE-END PROJECTION: a provider segment text ending on terminal
        # punctuation marks a model-detected sentence boundary; re-attach that
        # terminal char to the bare last word so the snapper sees a native sent-end.
        if provider_text and _segment_text_ends_sentence(provider_text):
            terminal = provider_text.rstrip(_TRAILING_STRIP)[-1]
            words = _project_sentence_end(words, terminal)

        segments.append(Segment(start=ss, end=se, text=text))
        word_segments.append(WordSegment(start=ss, end=se, words=tuple(words)))

    return Transcript(
        duration=eff_duration,
        language=language,
        engine=engine,
        segments=tuple(segments),
        word_segments=tuple(word_segments),
    )
