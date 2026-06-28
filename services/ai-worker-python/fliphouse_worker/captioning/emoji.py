"""PURE: sparse semantic emoji stamping over GROUPED caption lines (P3-A8).

Stamps at most one single-scalar emoji per N lines onto a keyword-bearing word, immutably.
Every A8 invariant (density cap, <=1-per-line, never-line-start, allowlist clamp, capability/
OFF gate) lives HERE and is unit-asserted on plain values. No emoji codepoint is chosen that
is not a curated, Emoji_Presentation=Yes SINGLE Unicode scalar — so harfbuzz shaping is
deterministic, the golden is pinnable, and the codepoint always falls back to the vendored
Noto Color Emoji face (the runtime capability probe + build smoke guard the colour render).
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import replace

from .ass import CaptionLine
from .segments import CaptionWord

# Each value is exactly ONE Unicode scalar with Emoji_Presentation=Yes (default-emoji; NO
# VS16 / ZWJ / skin-tone / flag / keycap) → deterministic shaping + a Montserrat-absent
# codepoint that falls back to the Noto colour face. The integrity test pins the exact
# codepoint set as a literal, so a future text-presentation entry cannot be added silently.
KEYWORD_EMOJI: dict[str, str] = {
    "деньги": "\U0001f4b0",
    "доход": "\U0001f4b0",
    "прибыль": "\U0001f4b0",
    "выручка": "\U0001f4b0",
    "рост": "\U0001f4c8",
    "масштаб": "\U0001f4c8",
    "выросли": "\U0001f4c8",
    "огонь": "\U0001f525",
    "топ": "\U0001f525",
    "круто": "\U0001f525",
    "идея": "\U0001f4a1",
    "мысль": "\U0001f4a1",
    "быстро": "⚡",
    "время": "⚡",
    "скорость": "⚡",
    "да": "✅",
    "согласен": "✅",
    "верно": "✅",
    "запуск": "\U0001f680",
    "старт": "\U0001f680",
    "цель": "\U0001f3af",
    "точно": "\U0001f3af",
    # EN parity
    "money": "\U0001f4b0",
    "growth": "\U0001f4c8",
    "fire": "\U0001f525",
    "idea": "\U0001f4a1",
    "fast": "⚡",
}
ALLOWED_EMOJI: frozenset[str] = frozenset(KEYWORD_EMOJI.values())

# The vetted scalar set, pinned as a LITERAL so the integrity guard is NON-vacuous and the
# runtime cmap probe checks the EXACT coverage. Adding a keyword whose glyph is not here
# fails the integrity test.
ALLOWED_EMOJI_CODEPOINTS: frozenset[int] = frozenset(
    {0x1F4B0, 0x1F4C8, 0x1F525, 0x1F4A1, 0x26A1, 0x2705, 0x1F680, 0x1F3AF}
)


def _normalize(text: str) -> str:
    """casefold + strip surrounding caption punctuation (the RU/EN salience key)."""
    return text.casefold().strip(" .,!?:;…—«»\"'()")


def emoji_for(word_text: str) -> str:
    """Pure deterministic lookup; '' on miss. Values are single-scalar in ALLOWED_EMOJI."""
    return KEYWORD_EMOJI.get(_normalize(word_text), "")


def _emphasis(word: CaptionWord) -> bool:
    """A4 emphasis, read defensively so a future field-shape change never raises here."""
    return bool(getattr(word, "emphasis", False))


def _select_stamp(line: CaptionLine, emoji_for_fn: Callable[[str], str]) -> tuple[int, str]:
    """Pick (index, glyph) for the <=1 stamp on this line, or (-1, '').

    Priority — decouples lookup from a single positional slot so the dev/heuristic path fires
    and A4 emphasis can NEVER suppress a mappable keyword:
      1. the A4-emphasised word, IF it maps;
      2. else the LAST word, IF it maps;
      3. else the nearest-to-end CONTENT word that maps, scanning len-1..lo, where lo=0 for a
         single-word line and lo=1 for a multiword line (NEVER line-start index 0 of a
         multiword line — the emoji always trails content).
    Exactly one index is ever returned → <=1 per LINE is structural.
    """
    words = line.words
    if not words:
        return -1, ""
    for k, w in enumerate(words):
        if _emphasis(w):
            g = emoji_for_fn(w.text)
            if g:
                return k, g
            break  # the emphasised word does not map → fall through to the end-scan
    lo = 0 if len(words) == 1 else 1
    for k in range(len(words) - 1, lo - 1, -1):
        g = emoji_for_fn(words[k].text)
        if g:
            return k, g
    return -1, ""


def apply_line_emoji(
    lines: Sequence[CaptionLine],
    *,
    emoji_capable: bool,
    density_n: int,
    emoji_for_fn: Callable[[str], str] = emoji_for,
    allowed_emoji: frozenset[str] = ALLOWED_EMOJI,
) -> list[CaptionLine]:
    """Stamp at most one emoji per ``density_n`` lines onto the selected word, immutably.

    Invariants (all enforced here; caller/model never trusted):
      - capability gate: ``emoji_capable`` False → identity return (no emoji ever).
      - OFF: ``density_n <= 0`` → identity return (byte-identical default path).
      - density cap: a stamp resets a cooldown; the next ``density_n-1`` lines get none.
      - <=1 per LINE: ``_select_stamp`` returns exactly one index.
      - allowlist clamp: a glyph not in ``allowed_emoji`` (or '') is dropped — keeps any future
        selector deterministic and ASS-injection-safe.
      - immutable rebuild: ``replace(word, emoji=glyph)`` then ``replace(line, words=...)``.
    """
    if not emoji_capable or density_n <= 0:
        return list(lines)
    out: list[CaptionLine] = []
    since = density_n  # allow an immediate first stamp
    for line in lines:
        idx, glyph = _select_stamp(line, emoji_for_fn) if since >= density_n else (-1, "")
        if glyph not in allowed_emoji:  # '' or non-allowlisted → drop
            idx, glyph = -1, ""
        if glyph:
            words = tuple(
                replace(w, emoji=glyph) if k == idx else w for k, w in enumerate(line.words)
            )
            out.append(replace(line, words=words))
            since = 1
        else:
            out.append(line)
            since += 1
    return out
