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
