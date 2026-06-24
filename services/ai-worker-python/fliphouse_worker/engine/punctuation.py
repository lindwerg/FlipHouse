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

from collections.abc import Callable, Sequence

# Dependency-injection seam (mirrors the engine's ``llm_fn``/``highlight_fn``/
# ``topic_break_fn`` convention). Given the flat word list, a ``PunctFn`` returns a
# per-word "this word TERMINATES a sentence" mask (one bool per word). It is the
# clean hook for a permissive RU punctuation-restoration model — the sanctioned
# production adapter runs RUPunct_small (MIT, CPU) and may refine spans with razdel
# (MIT); silero_te (CC-BY-NC) is BANNED and never wired here. The engine ships
# PURE: ``punct_fn`` defaults to ``None`` (today's pause-only heuristic, byte-for-
# byte unchanged), so the model/lib lives OUTSIDE the worker package and the 100%
# coverage gate stays green with no optional-import branch.
PunctFn = Callable[[Sequence[dict]], Sequence[bool]]

# ── tuning constants ────────────────────────────────────────────────────────
# A silence at least this long between two words is structural: in RU speech a
# real sentence/clause break carries a longer pause than a within-phrase breath.
# This MEDIUM pause still needs corroboration (a capitalized / discourse-opener
# next word) before it counts as a sentence end — a 0.45s breath alone is weak.
SENT_PAUSE_S = 0.45
# A LONG silence is a sentence end ON ITS OWN — no capitalization / discourse cue
# required. Rationale: in RU monologue speech a 0.7s+ gap is a strong prosodic
# clause/sentence boundary, and a clip that ends there reads as a FINISHED beat,
# never mid-word. This matters because GigaAM-v3 almost never emits terminal
# punctuation or capitalization, so the medium-pause rule (which needs a
# fresh-start cue) flags almost nothing in real monologue output — leaving the
# tail snapper with no sentence-end targets and landing the cut mid-thought.
# This rule is SAFE: a long silence is a real stop; at worst it lands on a clause
# edge, which still reads as a complete beat — far better than a mid-thought cut.
LONG_PAUSE_S = 0.7
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
# STOP signals — a thought is being wrapped up / concluded. These are genuine
# WRAP-UP markers only. A mid-thought CONNECTIVE ("и поэтому", "так что", "а потом")
# is deliberately EXCLUDED: the highlight prompt forbids ending a clip on it, so
# treating it as a preferred sentence-end would directly contradict that and drag a
# clip's tail onto a mid-thought cut (the exact founder complaint).
STOP_MARKERS: tuple[tuple[str, ...], ...] = (
    ("вот", "и", "всё"),
    ("вот", "и", "все"),  # ASR often drops the ё → "все"
    ("в", "итоге"),
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


def annotate_sentence_ends(words: Sequence[dict], *, punct_fn: PunctFn | None = None) -> list[dict]:
    """Flat word list → same list with a ``sent_end`` bool per word.

    When ``punct_fn`` is supplied (the injectable RU punctuation-restoration seam),
    its per-word ``True`` flags take PRECEDENCE: a word the model marks as a sentence
    terminus is flagged regardless of pause structure. This is the LOAD-BEARING fix
    for GigaAM ASR (no punctuation, no capitals), where the pause-only heuristic
    below flags almost nothing reliably and clips end mid-thought. The model output
    must be one bool per word; a length mismatch is IGNORED (fail-open to the pause
    heuristic) so a misbehaving adapter can never corrupt the boundary set.

    For every word the model did NOT flag (or whenever ``punct_fn`` is ``None`` —
    today's behavior, byte-for-byte), the conservative pause/discourse fallback
    applies. A word is then flagged a sentence end when ANY of these holds:

      * it already carries terminal punctuation (a punctuated transcript wins
        outright — we never override a real ``.``/``!``/``?``);
      * a STOP discourse marker ends AT this word (the thought is wrapped up);
      * a LONG pause (>= ``LONG_PAUSE_S``) follows — a long silence is a real stop
        ON ITS OWN, no fresh-start cue required (crucial for GigaAM-v3, which
        rarely capitalizes); or
      * a MEDIUM structural pause (>= ``SENT_PAUSE_S``) follows AND the next thought
        looks fresh — corroborated by the next word being capitalized OR opening
        with a START discourse marker. A medium pause alone is NOT enough (that is
        just a breath); requiring a fresh-start cue keeps the flag conservative.

    PURE: returns NEW dicts, never mutates the input words.
    """
    norms = [_norm(w["word"]) for w in words]
    flags = [False] * len(words)
    model_flags: list[bool] | None = None
    if punct_fn is not None:
        candidate = list(punct_fn(words))
        # Fail-open: only trust a model mask that aligns 1:1 with the words; a
        # length mismatch (a buggy/partial adapter) is dropped, not applied.
        if len(candidate) == len(words):
            model_flags = [bool(flag) for flag in candidate]
    for i, word in enumerate(words):
        if model_flags is not None and model_flags[i]:
            flags[i] = True  # model-confirmed sentence terminus wins outright
            continue
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
        if gap >= LONG_PAUSE_S:
            flags[i] = True  # long silence is a sentence end on its own
        elif gap >= SENT_PAUSE_S and (
            _is_capitalized(words[i + 1]["word"]) or starts_discourse(norms, i + 1)
        ):
            flags[i] = True
    return [{**w, "sent_end": flag} for w, flag in zip(words, flags, strict=True)]
