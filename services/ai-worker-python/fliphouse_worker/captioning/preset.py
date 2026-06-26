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
