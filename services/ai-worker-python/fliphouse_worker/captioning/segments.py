"""PURE: slice the ASR ``word_segments`` to a clip window + offset to clip-relative t=0.

``word_segments`` is the doc 01 §2 flat list ``[{start, end, words:[{word, start,
end}]}]`` where every ``word`` carries a LEADING SPACE (the captacity convention).
For one clip cut to ``[clip_start, clip_end)`` (CLOSED-OPEN on the word START), we
keep the words whose start falls in the window, ``.lstrip()`` the leading-space
token BEFORE it is measured (REQUIRED — libass ``\\k`` boundaries and per-word
widths are computed off the visible glyphs, so a stray leading space throws them
off), and shift every timing so the clip begins at ``t=0``.

Fail-OPEN: any malformed segment / word (missing key, wrong type) is skipped and
an unparseable top-level input yields ``[]`` — captions must never block a clip,
mirroring ``caption_band``'s fail-open contract.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class CaptionWord:
    """One visible word with CLIP-RELATIVE timing (leading space already stripped)."""

    text: str
    start: float
    end: float


def slice_and_offset_words(
    word_segments: object, clip_start: float, clip_end: float
) -> list[CaptionWord]:
    """Words whose start ∈ ``[clip_start, clip_end)``, lstripped + offset to t=0.

    Closed-open on the word START time so a word landing exactly on the clip
    boundary belongs to exactly one clip. A start before the window (rounding
    slop) clamps the OFFSET to ``0.0`` only for in-window words; out-of-window
    words are dropped. Returns ``[]`` on any non-iterable / malformed input.
    """
    if not isinstance(word_segments, Iterable) or isinstance(word_segments, (str, bytes)):
        return []

    out: list[CaptionWord] = []
    for seg in word_segments:
        if not isinstance(seg, Mapping):
            continue
        words = seg.get("words")
        if not isinstance(words, Iterable) or isinstance(words, (str, bytes)):
            continue
        for raw in words:
            word = _parse_word(raw, clip_start, clip_end)
            if word is not None:
                out.append(word)
    return out


def _parse_word(raw: object, clip_start: float, clip_end: float) -> CaptionWord | None:
    """One raw word → CaptionWord if in-window + non-empty after lstrip, else None."""
    if not isinstance(raw, Mapping):
        return None
    try:
        start = float(raw["start"])
        end = float(raw["end"])
        text = str(raw["word"]).lstrip()
    except (KeyError, TypeError, ValueError):
        return None
    if not text:
        return None
    if start < clip_start or start >= clip_end:  # closed-open on the word start
        return None
    rel_start = round(max(0.0, start - clip_start), 3)
    rel_end = round(max(rel_start, end - clip_start), 3)
    return CaptionWord(text=text, start=rel_start, end=rel_end)
