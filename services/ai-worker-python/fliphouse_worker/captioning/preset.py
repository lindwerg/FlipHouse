"""PURE: ``CaptionPreset`` — the value object that holds every caption look knob.

P3-A0 scaffold. The ASS builder (``ass.py``) takes a ``preset: CaptionPreset =
DEFAULT_PRESET`` and reads each rendered attribute off it instead of off a module
constant, so a new look is just a new ``CaptionPreset`` value — no churn to the
pinned golden. ``DEFAULT_PRESET`` is built FROM the existing ``ass.py`` constants,
so its output is BYTE-IDENTICAL to the current production caption (zero regression
for live clips). Later P3 steps EXTEND this preset with their own knob (lead_ms,
pop, fade, keyword/emoji, band-mode) — each wired + tested in its own step so no
field is ever an inert placeholder.

Frozen + fully typed: a preset is an immutable snapshot chosen per job.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# Both timing knobs are non-negative offsets; a negative value is meaningless (it would
# silently no-op in the builder) so an out-of-range preset is rejected at construction.
_NON_NEGATIVE_MS_FIELDS: tuple[str, ...] = ("lead_ms", "fade_in_ms")

# P3-A8 — non-negative integer knobs (kept separate from the ms fields so the ms semantics
# stay clean). MODULE constant, never a dataclass field.
_NON_NEGATIVE_INT_FIELDS: tuple[str, ...] = ("emoji_every_n",)

# P3-A4 — inline-\c colour fields must be strict ASS hex so a colour string can NEVER carry a
# ``}`` or ``\fn`` ASS-breakout that would pull a non-OFL font into the libass raster path.
# Presets are built at import → a bad constant trips tests, never a paid render. MODULE-level
# constant (never a dataclass field). Accepts &Hbbggrr / &Haabbggrr (+ optional trailing &).
_ASS_COLOUR_RE = re.compile(r"^&H(?:[0-9A-Fa-f]{6}|[0-9A-Fa-f]{8})&?$")

# P3-A6 — libass V4+ BorderStyle (Style field#16) domain. ONLY {1, 3} are real, portable
# libass capabilities:
#   1 = outline + drop-shadow (DEFAULT, byte-identical golden)
#   3 = opaque box per line; box FILL = OutlineColour (alpha byte honoured → can be made
#       translucent), box padding = Outline, drop-shadow = Shadow.
# BorderStyle=2 (outline + opaque box) is meaningless for a single-band look and
# BorderStyle=4 is NOT a libass capability (libass special-cases only ==3; every other
# value renders as plain outline). Both are rejected at construction (fail-fast). This is a
# MODULE-level constant (mirroring _NON_NEGATIVE_MS_FIELDS) so it never becomes a dataclass
# field — a class-body annotated assignment would turn it into a spurious 12th field.
_ALLOWED_BORDER_STYLES: frozenset[int] = frozenset({1, 3})


@dataclass(frozen=True)
class CaptionPreset:
    """An immutable caption look. A0 carries the currently-rendered style knobs.

    Every field maps to exactly one rendered ASS token (font/colour/border), so
    ``dataclasses.replace``-ing a single field moves a single token — that is what
    makes adding a new look safe against the pinned golden.
    """

    font_name: str
    font_size: int
    base_colour: str
    active_colour: str
    outline_colour: str
    shadow_colour: str
    outline_px: int
    shadow_px: int

    # P3-A2 — read-ahead: the active-word highlight starts ``lead_ms`` BEFORE the word
    # is spoken (a Submagic retention cue). 0 in DEFAULT_PRESET → byte-identical golden;
    # expressive presets use ~70. Clamped to ≥0 and to the previous word's start so the
    # per-word windows stay monotonic and non-overlapping (exactly one active word).
    lead_ms: int = 0

    # P3-A3 — active-word pop: when True the spoken word scales base→peak→base via two
    # libass ``\t`` INSIDE its own per-word event (peak/rise/fall = POP_PEAK_PCT /
    # POP_RISE_MS / POP_FALL_MS in ass.py), the peak clamped per word against the REAL
    # font metrics so the popped word never grows off the frame. With pop ON every word
    # re-asserts its base ``\fscx``/``\fscy`` so the active word's animation cannot bleed
    # forward in the same event. False in DEFAULT_PRESET → byte-identical golden;
    # expressive presets set pop=True (composes with lead_ms).
    pop: bool = False

    # P3-A5 — one-shot entrance fade: when >0 the line fades in once via a single libass
    # ``\fad(fade_in_ms, 0)`` (fade-in only) placed ONLY on the FIRST per-word event of
    # the line. Interior word-events carry NO ``\fad`` — each interior event re-spans the
    # whole line, so a fade on every event would re-fade the line per word and read as a
    # STROBE. The value is clamped per line to strictly below the first event's on-screen
    # window so the entrance always completes inside the word window. 0 in DEFAULT_PRESET →
    # byte-identical golden; expressive presets use ~150 (composes with lead_ms and pop —
    # ``\fad`` line-alpha is orthogonal to ``\t`` scale).
    fade_in_ms: int = 0

    # P3-A6 — caption contrast band. libass V4+ BorderStyle (Style field#16):
    #   1 = outline + drop-shadow (DEFAULT) — substituting {preset.border_style} with the
    #       default 1 reproduces the literal '1' at the BorderStyle column → golden
    #       byte-identical.
    #   3 = opaque box per LINE; box FILL = ``outline_colour`` (REPURPOSED — not the glyph
    #       outline), padding = ``outline_px``, drop-shadow = ``shadow_px``. The box reads
    #       as a dark band behind the text. To make the band TRANSLUCENT, put an alpha byte
    #       on ``outline_colour`` (e.g. &H80101010 ≈ 50% black) — libass honours the
    #       box-colour alpha in bs=3. ASS alpha is INVERTED (AA byte: 00=opaque,
    #       FF=transparent). Domain {1, 3} (see _ALLOWED_BORDER_STYLES); 1 in DEFAULT_PRESET
    #       → byte-identical golden, expressive band presets use 3.
    border_style: int = 1

    # P3-A4 — keyword second colour: an inline ``\c`` override on the at-most-one salient
    # word per LINE (precedence active>keyword>base). None in DEFAULT_PRESET → the keyword
    # branch is dead → byte-identical golden; expressive A9 presets set a NEUTRAL accent
    # (paired with the loud active_colour). No Style slot (inline \c only). MUST stay
    # preset-derived, NEVER request-derived (_select_caption_preset resolves curated presets
    # by NAME and never reads a raw colour from the request). Validated &Hbbggrr/&Haabbggrr.
    keyword_colour: str | None = None

    # P3-A8 — emoji density: at most one sparse semantic emoji per N caption lines. 0 in
    # DEFAULT_PRESET → OFF → byte-identical golden; expressive A9 presets (Поп/Караоке) use
    # N=2..3 once the Noto Color Emoji font + build guard land (until then emoji stays OFF and
    # the capability probe fails closed to no-emoji). No Style slot (the glyph rides the host
    # word's existing Dialogue run). Validated >= 0.
    emoji_every_n: int = 0

    def __post_init__(self) -> None:
        """Reject a structurally-invalid preset: the ms offsets must be non-negative and
        ``border_style`` must be a real libass capability (``{1, 3}``).

        A negative ``lead_ms``/``fade_in_ms`` would silently no-op in the builder
        (clamped away), and an out-of-domain ``border_style`` (e.g. 4) would silently
        render as plain outline on every build, so making the invalid state
        unrepresentable surfaces the bug at the call site instead of producing a
        silently-wrong render.
        """
        for field in (*_NON_NEGATIVE_MS_FIELDS, *_NON_NEGATIVE_INT_FIELDS):
            value = getattr(self, field)
            if value < 0:
                raise ValueError(f"{field} must be >= 0, got {value}")
        if self.border_style not in _ALLOWED_BORDER_STYLES:
            raise ValueError(f"border_style must be one of {{1, 3}}, got {self.border_style}")
        # Inline-\c colour fields must be strict ASS hex (no }/\ breakout). base/active are
        # always present; keyword_colour only when set (None = OFF).
        for name in ("base_colour", "active_colour"):
            if not _ASS_COLOUR_RE.fullmatch(getattr(self, name)):
                raise ValueError(f"{name} must be ASS hex (&Hbbggrr / &Haabbggrr)")
        if self.keyword_colour is not None and not _ASS_COLOUR_RE.fullmatch(self.keyword_colour):
            raise ValueError("keyword_colour must be ASS hex (&Hbbggrr / &Haabbggrr) or None")
