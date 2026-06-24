"""Concrete RapidFuzz (MIT) adapter for the ``align_fn`` seam in :mod:`.align`.

:mod:`.align` is PURE: it turns the LLM's verbatim ``start_phrase``/``end_phrase``
into word-index spans through an INJECTED matcher, never importing a fuzzy lib so
the engine core stays dependency-free. THIS module is that injected matcher, made
concrete with **RapidFuzz** (MIT, pure C/Python, no model weights). It is wired into
the production score path (``stages/_types.py`` → ``recall_candidates(align_fn=…)``)
so a clip's bounds anchor to the real words of the LLM-identified COMPLETE sentence
— the END lands on the last word of a finished thought, not the model's noisy float.

Why RapidFuzz and not exact match: GigaAM ASR and the LLM disagree on token spelling
(dropped ё, merged clitics, casing), so the phrase the model copied "verbatim" is
rarely byte-identical to the ASR word stream. A token-level fuzzy ratio absorbs that
drift. Why anchored near ``near_t``: a short RU phrase ("и поэтому", "вот так") repeats
across a 2-hour transcript; scoring only a window of words around the LLM's float time
keeps the match on the RIGHT occurrence instead of a louder one elsewhere.

Fail-closed: below ``MIN_MATCH_RATIO`` (a weak/absent match) the adapter returns
``None`` so :func:`align_phrase_to_words` falls open to the existing float→refine path.
"""

from __future__ import annotations

from collections.abc import Sequence

from rapidfuzz import fuzz

from .punctuation import _norm as _norm_word

# A token-level similarity (0-100) below this is treated as "no confident match":
# the adapter returns None and the caller keeps the LLM float bound. 80 tolerates
# ASR/LLM spelling drift (a dropped vowel, a merged clitic) while still rejecting a
# coincidental window that merely shares a couple of common words.
MIN_MATCH_RATIO = 80.0

# Only score word windows whose START sits within this many seconds of the LLM's
# float anchor. This is the repeated-phrase disambiguator: a phrase that occurs
# many times across a long transcript is matched to the occurrence the model
# actually meant (the one near its reported time), never a louder one elsewhere.
ANCHOR_WINDOW_S = 20.0


def _phrase_tokens(phrase: str) -> list[str]:
    """Normalize a phrase to a list of bare matchable tokens (``''`` tokens dropped)."""
    return [t for t in (_norm_word(w) for w in phrase.split()) if t]


def _window_text(words: Sequence[dict], i: int, span: int) -> str:
    """Normalized, space-joined text of ``words[i : i+span]`` (the candidate window)."""
    return " ".join(_norm_word(words[j]["word"]) for j in range(i, i + span))


def align_fn(phrase: str, words: Sequence[dict], near_t: float) -> tuple[int, int] | None:
    """Resolve ``phrase`` to the best ``(i_start, i_end)`` word span near ``near_t``.

    Slides a window the width of the phrase's token count across ``words``, scoring
    each window (whose start time is within ``ANCHOR_WINDOW_S`` of ``near_t``) by
    RapidFuzz token-sort ratio against the phrase. Returns the inclusive index span
    of the highest-scoring window when it clears ``MIN_MATCH_RATIO``; otherwise
    ``None`` (fail-open to the float bound). Ties break toward the window CLOSEST to
    ``near_t`` so a repeated phrase resolves to the intended occurrence.

    PURE: reads ``words`` (each ``{"word", "start", "end"}``), never mutates them.
    """
    tokens = _phrase_tokens(phrase)
    span = len(tokens)
    if span == 0 or span > len(words):
        return None

    target = " ".join(tokens)
    best_score = -1.0
    best_i: int | None = None
    best_dist = float("inf")
    for i in range(len(words) - span + 1):
        if abs(float(words[i]["start"]) - near_t) > ANCHOR_WINDOW_S:
            continue
        score = fuzz.token_sort_ratio(target, _window_text(words, i, span))
        dist = abs(float(words[i]["start"]) - near_t)
        # Strictly-better score wins; an equal score wins only if strictly closer to
        # the anchor — so the nearest occurrence breaks a tie deterministically.
        if score > best_score or (score == best_score and dist < best_dist):
            best_score = score
            best_dist = dist
            best_i = i

    if best_i is None or best_score < MIN_MATCH_RATIO:
        return None
    return best_i, best_i + span - 1
