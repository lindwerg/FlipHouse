"""Verbatim phrase → word-timestamp alignment (dormant-path resilience).

The dormant LLM cherry-pick path (``highlights.py`` + ``recall.recall_candidates``)
asks the model for a ``start_phrase``/``end_phrase`` copied VERBATIM from the
transcript. This module turns those phrases into precise ``(start, end)`` seconds
by locating the matching first/last WORDS and reading their timestamps — so a
clip's bounds are token-anchored, not anchored on the model's noisy float guess.

PURE and fail-open. The actual fuzzy matcher (RapidFuzz, MIT — ``process``/
``partial_ratio`` over a ±20s window anchored on the LLM float to disambiguate a
phrase that repeats) is INJECTED via ``align_fn`` from OUTSIDE the worker package.
RapidFuzz is NEVER imported here, so the wheel + the 100% coverage gate stay clean
and no GPL matcher (FuzzyWuzzy) is pulled in. When no ``align_fn`` is supplied (the
state until the adapter is wired), every call returns ``None`` and the caller keeps
the LLM float bound.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

# Injectable matcher: (phrase, words, near_t) → the (i_start, i_end) word-index
# span the phrase aligns to, or None when no confident match exists near ``near_t``.
AlignFn = Callable[[str, Sequence[dict], float], tuple[int, int] | None]


def align_phrase_to_words(
    phrase: str,
    words: Sequence[dict],
    near_t: float,
    *,
    align_fn: AlignFn | None = None,
) -> tuple[int, int] | None:
    """Locate ``phrase`` in ``words`` near ``near_t`` → its ``(i_start, i_end)`` span.

    Fail-open: with no ``align_fn`` (default) or an empty phrase / word list, return
    ``None`` so the caller keeps its existing (float) bound. The injected matcher is
    responsible for fuzzy tolerance (ASR drift) and for disambiguating a repeated
    phrase by proximity to ``near_t``.
    """
    if align_fn is None or not phrase or not words:
        return None
    return align_fn(phrase, words, near_t)


def phrase_boundaries(
    h: dict, words: Sequence[dict], *, align_fn: AlignFn | None = None
) -> tuple[float, float] | None:
    """Highlight dict → ``(start, end)`` seconds from its verbatim phrase spans.

    Aligns ``start_phrase`` near the LLM ``start_time`` and ``end_phrase`` near the
    LLM ``end_time``; returns ``(words[i_start].start, words[i_end].end)`` when BOTH
    resolve and the span is non-degenerate (start before end). Returns ``None`` on
    any miss (fail-open to the float locator), so a model that omits the phrases —
    or a deployment with no ``align_fn`` — keeps today's behavior exactly.
    """
    start_phrase = str(h.get("start_phrase") or "")
    end_phrase = str(h.get("end_phrase") or "")
    if not start_phrase or not end_phrase:
        return None

    near_start = float(h["start_time"])
    near_end = float(h["end_time"])
    start_span = align_phrase_to_words(start_phrase, words, near_start, align_fn=align_fn)
    end_span = align_phrase_to_words(end_phrase, words, near_end, align_fn=align_fn)
    if start_span is None or end_span is None:
        return None

    i_start = start_span[0]
    i_end = end_span[1]
    start_t = float(words[i_start]["start"])
    end_t = float(words[i_end]["end"])
    if end_t <= start_t:
        return None  # degenerate / out-of-order match — fail open to the float bound
    return start_t, end_t
