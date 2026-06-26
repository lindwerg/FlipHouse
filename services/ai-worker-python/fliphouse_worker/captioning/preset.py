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

from dataclasses import dataclass

# Both timing knobs are non-negative offsets; a negative value is meaningless (it would
# silently no-op in the builder) so an out-of-range preset is rejected at construction.
_NON_NEGATIVE_MS_FIELDS: tuple[str, ...] = ("lead_ms", "fade_in_ms")


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

    def __post_init__(self) -> None:
        """Reject a structurally-invalid preset: the ms offsets must be non-negative.

        A negative ``lead_ms``/``fade_in_ms`` would silently no-op in the builder
        (clamped away), so making the invalid state unrepresentable surfaces the bug at
        the call site instead of producing a silently-wrong render.
        """
        for field in _NON_NEGATIVE_MS_FIELDS:
            value = getattr(self, field)
            if value < 0:
                raise ValueError(f"{field} must be >= 0, got {value}")
