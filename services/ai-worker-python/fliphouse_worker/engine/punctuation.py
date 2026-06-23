"""RU sentence-boundary restoration for boundary snapping (REFRAME Phase 3).

The founder complaint is that clips START/END mid-thought. ``recall.refine_boundaries``
already prefers a SENTENCE-END word when snapping a clip's tail — but it decides
"is this a sentence end?" by looking for terminal PUNCTUATION (``.``/``!``/``?``/``…``).
RU ASR (GigaAM-v3) almost never emits punctuation, so that signal is empty and the
snapper falls back to "any breath", landing the cut on a random in-sentence pause.

This module RESTORES a per-word sentence-end signal WITHOUT a model, so the gate
stays CPU-only and license-clean (no checkpoint at all). It is a deliberate
HEURISTIC restorer (capitalization + pause structure + RU discourse cues), chosen
because no small, permissively-licensed (MIT/Apache/BSD) RU punctuation-restoration
model is cleanly available to run inside the worker package's coverage gate. The
heuristic is conservative: it only marks a boundary it is fairly sure of, so a
false sentence-end never drags a clip's tail onto a mid-thought cut.

It feeds the EXISTING snapper: ``annotate_sentence_ends`` returns the same flat
``[{word,start,end}]`` word list with an added ``sent_end`` bool, which
``recall._gap_candidates`` reads instead of the punctuation-only ``_ends_sentence``.

It also exposes RU DISCOURSE MARKERS used as soft START/STOP signals: an opener
like "итак"/"короче" is a natural clip START; a closer like "вот и всё"/"в итоге"
is a natural clip STOP. These let a clip begin on a fresh thought and end on a
wrapped-up one even when no terminal punctuation exists.
"""

from __future__ import annotations

from collections.abc import Sequence

# ── tuning constants ────────────────────────────────────────────────────────
# A silence at least this long between two words is structural: in RU speech a
# real sentence/clause break carries a longer pause than a within-phrase breath.
SENT_PAUSE_S = 0.45
# A capitalized NEXT word right after a pause corroborates a sentence start. RU
# ASR rarely capitalizes, so capitalization is a BONUS cue, never required.
# A discourse opener (below) right after a pause is the strongest no-punctuation
# sentence-start cue we have.

# Terminal punctuation (kept here so the heuristic still honors a punctuated
# transcript — e.g. a cloud fallback provider that DOES emit punctuation).
_SENTENCE_END_CHARS = (".", "!", "?", "…")
_TRAILING_STRIP = "\"'`)]}»”’"  # closing quotes/brackets stripped before the char check

# RU discourse markers. Stored lowercased & punctuation-free for matching; a
# marker may be multi-word ("так вот"), so matching is done on word n-grams.
# START signals — a fresh thought is being opened.
START_MARKERS: tuple[tuple[str, ...], ...] = (
    ("итак",),
    ("короче",),
    ("и", "вот"),
    ("так", "вот"),
    ("смотри",),
    ("слушай",),
)
# STOP signals — a thought is being wrapped up / concluded.
STOP_MARKERS: tuple[tuple[str, ...], ...] = (
    ("вот", "и", "всё"),
    ("вот", "и", "все"),  # ASR often drops the ё → "все"
    ("в", "итоге"),
    ("и", "поэтому"),
    ("вот", "так"),
)

_MAX_MARKER_LEN = max(len(m) for m in (*START_MARKERS, *STOP_MARKERS))


def _clean_token(word: str) -> str:
    """Lowercased, surrounding-whitespace-free, trailing-quote-stripped token."""
    return word.strip().rstrip(_TRAILING_STRIP)


def ends_with_terminal_punct(word: str) -> bool:
    """True if a token already carries terminal punctuation (punctuated transcript)."""
    return _clean_token(word).endswith(_SENTENCE_END_CHARS)


def _norm(word: str) -> str:
    """Lowercase, strip surrounding/terminal punctuation → a bare matchable token."""
    token = _clean_token(word).lower()
    return token.strip(".,!?…:;\"'`()[]{}«»”’-")


def _is_capitalized(word: str) -> bool:
    """True if the first alphabetic char of the token is upper-case (a start cue)."""
    token = _clean_token(word)
    for ch in token:
        if ch.isalpha():
            return ch.isupper()
    return False


def _marker_at(norms: Sequence[str], idx: int, markers: Sequence[tuple[str, ...]]) -> bool:
    """True if any marker n-gram matches the normalized words starting at ``idx``."""
    for marker in markers:
        end = idx + len(marker)
        if end <= len(norms) and tuple(norms[idx:end]) == marker:
            return True
    return False


def starts_discourse(norms: Sequence[str], idx: int) -> bool:
    """True if a START discourse marker begins at word ``idx`` (fresh-thought opener)."""
    return _marker_at(norms, idx, START_MARKERS)


def ends_discourse(norms: Sequence[str], idx: int) -> bool:
    """True if a STOP discourse marker begins at word ``idx`` (thought-wrap closer)."""
    return _marker_at(norms, idx, STOP_MARKERS)


def annotate_sentence_ends(words: Sequence[dict]) -> list[dict]:
    """Flat word list → same list with a heuristic ``sent_end`` bool per word.

    A word is flagged a sentence end when ANY of these holds:

      * it already carries terminal punctuation (a punctuated transcript wins
        outright — we never override a real ``.``/``!``/``?``);
      * a STOP discourse marker ends AT this word (the thought is wrapped up); or
      * a structural pause (>= ``SENT_PAUSE_S``) follows AND the next thought looks
        fresh — corroborated by the next word being capitalized OR opening with a
        START discourse marker. The pause alone is NOT enough (that is just a
        breath); requiring a fresh-start cue keeps the flag conservative.

    PURE: returns NEW dicts, never mutates the input words.
    """
    norms = [_norm(w["word"]) for w in words]
    flags = [False] * len(words)
    for i, word in enumerate(words):
        if ends_with_terminal_punct(word["word"]):
            flags[i] = True
            continue
        # A STOP marker that ENDS at word i (marker spans [j, i]).
        for span in range(1, _MAX_MARKER_LEN + 1):
            j = i - span + 1
            if j >= 0 and ends_discourse(norms, j) and j + span - 1 == i:
                flags[i] = True
                break
        if flags[i] or i + 1 >= len(words):
            continue
        gap = words[i + 1]["start"] - word["end"]
        if gap >= SENT_PAUSE_S and (
            _is_capitalized(words[i + 1]["word"]) or starts_discourse(norms, i + 1)
        ):
            flags[i] = True
    return [{**w, "sent_end": flag} for w, flag in zip(words, flags, strict=True)]
