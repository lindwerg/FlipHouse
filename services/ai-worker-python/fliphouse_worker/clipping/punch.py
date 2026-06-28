"""PURE: the hook punch-zoom envelope (P3-A7) — a time-varying center zoom into the 9:16 box.

The reframe renderer normally emits a STATIC ``crop=…,scale=…`` per segment, so an eased
zoom cannot live in the smoothing/segment layer (it averages to one level). A7 is a NEW
time-varying renderer: this module builds the PURE ffmpeg ``zoompan`` expression that
replaces the static ``scale={w}:{h}`` link, and proves the centered window stays inside the
base box for every frame.

Why ``zoompan`` (not ``scale=eval=frame``+``crop``): ``scale=eval=frame`` emits
varying-size frames and ``crop`` freezes ``in_w``/``in_h`` at config time, so a center crop
overshoots the live frame for all t>0 (a real defect no string-golden catches). ``zoompan``
rasterizes onto a FIXED ``s=WxH`` canvas (exact 9:16 every frame) and clamps the pan against
the LIVE frame width, so the idealized center-crop geometry is actually realized.

The envelope is keyed on ``zoompan``'s output-frame counter ``on`` (a 0-based integer),
NOT absolute filter ``t`` — so the punch fires at clip-relative frame 0 regardless of the
production ``-ss start`` seek, and a NOPTS first frame can never poison the expression.

This module is import-pure (no I/O); the only impure actor is ffmpeg executing the emitted
node, behind the already-faked ``render_fn``. Fail-CLOSED (geometry leg): a structurally
impossible envelope raises ``PunchZoomError`` at construction.
"""

from __future__ import annotations

from dataclasses import dataclass

# The output 9:16 column is ALREADY a tight crop of the source, so its pixel budget is
# limited; an upscale beyond this softens the whole frame. 1.12 is the researched 2026 hook
# ceiling for an already-cropped vertical column.
Z_MAX: float = 1.12
# Ease floor: below this the ease collapses to a single-frame pop (no perceptible curve).
DURATION_MIN_S: float = 0.05
# Ease ceiling: above this the whole clip never settles to the base framing.
DURATION_MAX_S: float = 1.0


class PunchZoomError(ValueError):
    """Fail-closed geometry error: an impossible / out-of-range punch envelope or wiring."""


@dataclass(frozen=True)
class PunchZoom:
    """Immutable hook punch-zoom envelope. Center-anchored ease-OUT cubic on output-frame time.

    ``Z(s) = z_hold + (z_open - z_hold) * (1 - clip(s/duration_s, 0, 1))**3`` where
    ``s = on / fps`` (``on`` = zoompan output-frame counter, 0-based). ``s=0`` → ``Z=z_open``
    (punched in); ``s>=duration_s`` → ``Z=z_hold`` (settled, holds). With ``z_hold==1.0``
    the clip snaps back to the exact base-box framing.
    """

    z_open: float  # zoom at s=0 (the hook); >= z_hold, <= Z_MAX
    z_hold: float = 1.0  # zoom the clip settles to; >= 1.0 (1.0 == exact base-box framing)
    duration_s: float = 0.25  # ease-out duration (seconds); DURATION_MIN_S..DURATION_MAX_S

    def __post_init__(self) -> None:
        # FAIL-CLOSED — mirrors compute_crop_box / CaptionPreset.__post_init__: an impossible
        # envelope is a config bug that must surface at the call site, not a silent no-op.
        if self.z_hold < 1.0:
            raise PunchZoomError(f"z_hold must be >= 1.0, got {self.z_hold}")
        if self.z_open < self.z_hold:
            raise PunchZoomError(f"z_open ({self.z_open}) must be >= z_hold ({self.z_hold})")
        if self.z_open > Z_MAX:
            raise PunchZoomError(f"z_open must be <= {Z_MAX}, got {self.z_open}")
        if not (DURATION_MIN_S <= self.duration_s <= DURATION_MAX_S):
            raise PunchZoomError(
                f"duration_s must be in [{DURATION_MIN_S}, {DURATION_MAX_S}], got {self.duration_s}"
            )


# The researched 2026 hook default: a 10% punch easing out over 250ms, settling to base.
HOOK_PUNCH: PunchZoom = PunchZoom(z_open=1.10)


def _num(x: float) -> str:
    """Deterministic ffmpeg-numeric formatter for golden stability.

    The ``duration_s`` bound keeps every emitted value out of ``:g`` scientific-notation
    territory (``DURATION_MIN_S=0.05`` → ``'0.05'``, never ``'5e-02'``).
    """
    return f"{x:g}"


def _z_expr(punch: PunchZoom, fps: float) -> str:
    """The ffmpeg scalar ``z=`` expression text (literal arithmetic ffmpeg evaluates).

    Keyed on ``on`` (output-frame counter) over ``fps*duration_s`` → 0-based, integer source,
    ``-ss``/NOPTS-immune. ``(z_open - z_hold)`` is left as literal subtraction so a Python
    float-repr artifact (e.g. ``1.1-1.0 == 0.10000000000000009``) never leaks into the golden.
    """
    return (
        f"({_num(punch.z_hold)}+({_num(punch.z_open)}-{_num(punch.z_hold)})"
        f"*pow(1-clip(on/({_num(fps)}*{_num(punch.duration_s)}),0,1),3))"
    )


def punch_zoom_chain(out_w: int, out_h: int, fps: float, punch: PunchZoom) -> str:
    """The single ``zoompan`` node that REPLACES ``scale={out_w}:{out_h}``.

    Zooms into the upstream base-box frame (``iw``×``ih``) by ``Z(on/fps)``, center-anchored,
    rasterized onto the constant canvas ``s={out_w}x{out_h}``. Splices between the static
    ``crop=Bw:Bh:Bx:By`` and ``setsar=1``. Output dims are the LITERAL constants ``out_w``,
    ``out_h`` so the 9:16 ratio is exact every frame; ``fps`` MUST equal the source fps so
    ``zoompan`` does not resample the frame rate.
    """
    z = _z_expr(punch, fps)
    # x/y: top-left of a centered window of width iw/zoom (height ih/zoom). ``zoom`` is the
    # per-frame value zoompan already evaluated from ``z=``, so the centering tracks live Z.
    return (
        f"zoompan=z='{z}'"
        f":x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)'"
        f":d=1:s={out_w}x{out_h}:fps={_num(fps)}"
    )


def _z_of_t(punch: PunchZoom, t: float) -> float:
    """Pure Python mirror of the emitted ``Z`` (``t == on/fps``). Used by the all-t property test."""
    p = min(max(t / punch.duration_s, 0.0), 1.0)
    return punch.z_hold + (punch.z_open - punch.z_hold) * (1.0 - p) ** 3
