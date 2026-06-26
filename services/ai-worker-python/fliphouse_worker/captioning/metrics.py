"""PURE-ish: real glyph-advance widths for the vendored caption font.

The caption look is calibrated for RUSSIAN speech, but the legacy width heuristic
(``estimate_line_width_px`` in ``ass.py``) multiplies ``len(text)`` by a single
``_GLYPH_ADVANCE_EM = 0.62`` — a LATIN mean. Cyrillic advances are markedly wider
(measured on the vendored Montserrat ExtraBold: RU lowercase ≈0.71·em, uppercase
≈0.82·em, Щ ≈1.14·em), so that heuristic UNDER-estimates a Russian line by 14–56 %.
A safety-critical width check (the A3 active-word *pop* must never grow a word off
the 1080 frame) therefore cannot reuse it — an under-estimate would silently permit
a pop that clips. This module reads the font's real ``hmtx`` advances so the pop
clamp has a TRUE upper bound per word.

The advance table is loaded once and cached (the font is a vendored, deterministic
asset shipped via ``package-data``, so this is effectively a constant lookup). A
glyph absent from the font's ``cmap`` falls back to a conservative ``1.0·em`` — wider
than any real glyph mean, so a missing-glyph word can only ever UNDER-pop, never clip.
This is deliberately decoupled from the legacy packer heuristic: recalibrating the
packer would churn the pinned caption golden, which is out of scope here.
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from fontTools.ttLib import TTFont, TTLibError  # type: ignore[import-untyped]

# The same static TTF libass resolves by family name at render time, shipped in the
# package via [tool.setuptools.package-data]. __file__-relative resolution works for
# both the source tree and the unzipped pip install used on the worker image.
_FONT_PATH: Path = Path(__file__).resolve().parent / "fonts" / "Montserrat-ExtraBold.ttf"

# Conservative advance (em) for a codepoint missing from the font cmap. Above every
# real glyph mean, so an unknown glyph can only make the pop clamp MORE cautious.
FALLBACK_ADVANCE_EM: float = 1.0


@lru_cache(maxsize=1)
def _advance_table_em() -> dict[int, float]:
    """``codepoint -> advance width in em`` for every glyph in the font's cmap.

    If the font is missing or unreadable (e.g. a broken wheel), returns an empty table
    so EVERY codepoint falls back to ``FALLBACK_ADVANCE_EM`` — pop captions then merely
    under-pop (the conservative upper bound suppresses the pop) instead of crashing the
    encode. The pop=False / DEFAULT_PRESET golden path never loads the font, so it is
    unaffected regardless.
    """
    try:
        font = TTFont(_FONT_PATH)
    except (OSError, TTLibError):
        return {}
    units_per_em = font["head"].unitsPerEm
    hmtx = font["hmtx"]
    cmap = font.getBestCmap()
    return {cp: hmtx[glyph_name][0] / units_per_em for cp, glyph_name in cmap.items()}


def text_width_em(text: str) -> float:
    """Sum of real glyph advances (in em) for ``text`` at scale 100 %.

    Codepoints missing from the font fall back to ``FALLBACK_ADVANCE_EM``. No kerning
    is applied — ASS positions glyphs by advance only, so the plain advance sum is the
    rendered pen width the pop clamp must bound.
    """
    table = _advance_table_em()
    return sum(table.get(ord(ch), FALLBACK_ADVANCE_EM) for ch in text)
