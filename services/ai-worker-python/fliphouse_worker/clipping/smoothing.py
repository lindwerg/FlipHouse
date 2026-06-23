"""Pure crop-trajectory builder (P2 dynamic-reframe; bbox-aware subject + zoom axis).

Turns per-sample face samples into a smoothed :class:`CropTrajectory`. Two smoothed
axes ride together, both reset hard at every precomputed scene cut so the crop never
glides across a shot boundary:

  * CENTER — a deadband holds the window still under small motion; the One-Euro
    filter follows larger pans.
  * ZOOM/SIZE — the subject box height is eased ASYMMETRICALLY (fast zoom-OUT to keep
    a subject in frame, slow cinematic zoom-IN) so :func:`crop_geometry.compute_crop_box`
    fits a steady window instead of pulsing frame-to-frame.

The TRACK-vs-GENERAL decision is PER SAMPLE. A sample's SUBJECT is: the single
active face; the UNION of 2-3 co-present faces (so a multi-person shot keeps
EVERYONE, never center-cropping the gap between heads); or GENERAL when there is
no face, the active face sits within ``edge_margin_frac`` of a frame edge, or the
shot is a true crowd (more than ``co_present_max`` faces).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field

from .crop_geometry import (
    GENERAL_MARK,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    subject_fits,
    union_box,
    union_contains_in_widest,
)
from .one_euro import OneEuroFilter

DEADBAND_FRAC: float = 0.10
SNAP_EPS_S: float = 0.30
EDGE_MARGIN_FRAC: float = 0.10  # active face this close to a frame edge → show whole frame
CO_PRESENT_MAX: int = 3  # 2..3 faces → union subject; more is a true crowd → GENERAL

# Asymmetric zoom/size easing factors per sample (fraction of the gap closed each step).
# Zoom-OUT (window grows to fit a returning/extra subject) is FAST so nobody is sliced;
# zoom-IN (window tightens) is SLOW for a cinematic settle.
ZOOM_OUT_EASE: float = 0.6
ZOOM_IN_EASE: float = 0.18


@dataclass(frozen=True)
class RawSample:
    """One sampled instant: the active face center plus EVERY co-present face box.

    ``face`` is the active (speaker) face used for center stickiness; ``faces`` are
    all co-present detections this frame, from which the SUBJECT is derived (the
    single face, or their union for 2-3 co-present heads). ``face_count`` is kept
    explicit for back-compat. A faceless sample has ``center_x=None`` and no faces.
    """

    t: float
    center_x: float | None
    face_count: int
    face: FaceBox | None = None
    faces: tuple[FaceBox, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class _Subject:
    """The resolved per-sample crop subject: a box + its center, or GENERAL (no box)."""

    box: FaceBox | None
    center_x: float | None
    is_general: bool


def _near_edge(center_x: float, src_w: int, edge_margin_frac: float) -> bool:
    """True when the active face center is within ``edge_margin_frac`` of either side."""
    margin = edge_margin_frac * src_w
    return center_x < margin or center_x > src_w - margin


def _resolve_subject(s: RawSample, src_w: int, src_h: int, edge_margin_frac: float) -> _Subject:
    """Per-sample subject: GENERAL, single active face, or the union of co-present faces.

    Co-present 2-3 faces collapse into ONE union box (everyone kept) whenever a single
    undistorted 9:16 crop can hold both — either a TIGHT padded fit or, failing that,
    the WIDEST source-fit window. Only when even the widest 9:16 cannot contain both
    (truly far apart) does the subject become the DOMINANT (largest) face. A single
    active face near a frame edge degrades to GENERAL (subject leaving into b-roll). A
    true crowd (> ``CO_PRESENT_MAX`` faces) or a faceless frame is GENERAL.
    """
    if s.center_x is None or s.face_count > CO_PRESENT_MAX:
        return _Subject(box=None, center_x=None, is_general=True)
    if s.face_count >= 2:
        u = union_box(s.faces)
        # Keep EVERYONE whenever a single undistorted 9:16 crop can hold both heads:
        #   1. TIGHT fit — the PADDED union fits a 9:16 column (comfortable breathing
        #      room around both heads), the preferred framing; OR
        #   2. WIDE fit — the union is too spread for the padded crop, but BOTH heads
        #      still sit inside the WIDEST source-fit 9:16 window. We then show both
        #      (smaller, in the max-width column) rather than punch into one head.
        # Only when even the widest 9:16 cannot contain both (truly far apart) do we
        # fall back to the DOMINANT (largest) face. (Split-screen is a later increment.)
        if u is not None and (
            subject_fits(u, src_w, src_h) or union_contains_in_widest(u, src_w, src_h)
        ):
            return _Subject(box=u, center_x=u.center_x, is_general=False)
        dom = max(s.faces, key=lambda f: f.area, default=None)
        if dom is None:
            return _Subject(box=None, center_x=None, is_general=True)
        return _Subject(box=dom, center_x=dom.center_x, is_general=False)
    if _near_edge(s.center_x, src_w, edge_margin_frac):
        return _Subject(box=None, center_x=None, is_general=True)
    return _Subject(box=s.face, center_x=s.center_x, is_general=False)


def _ease_zoom(current_h: float | None, target_h: float) -> float:
    """Asymmetric one-step ease of the subject height toward ``target_h``.

    First sample (or post-reset) passes through. Growing the window (zoom-OUT) eases
    fast so a returning/extra subject is never sliced; shrinking (zoom-IN) eases slow.
    """
    if current_h is None:
        return target_h
    ease = ZOOM_OUT_EASE if target_h > current_h else ZOOM_IN_EASE
    return current_h + ease * (target_h - current_h)


def _scaled_box(box: FaceBox, smoothed_h: float) -> FaceBox:
    """``box`` rescaled about its center to ``smoothed_h`` (keeps aspect → smooth zoom)."""
    if box.h <= 0:
        return box
    k = smoothed_h / box.h
    new_w = box.w * k
    return FaceBox(
        x=box.center_x - new_w / 2.0,
        y=box.center_y - smoothed_h / 2.0,
        w=new_w,
        h=smoothed_h,
        score=box.score,
    )


def _smooth_center(
    s_center: float, held: float, euro: OneEuroFilter, t: float, deadband: float
) -> tuple[float, float]:
    """Deadband-gated One-Euro center; returns ``(center, new_held)``."""
    if abs(s_center - held) < deadband:
        return held, held
    cx = euro.filter(s_center, t)
    return cx, cx


def build_trajectory(
    samples: Sequence[RawSample],
    scene_cut_times: Sequence[float],
    src_w: int,
    src_h: int,
    *,
    deadband_frac: float = DEADBAND_FRAC,
    edge_margin_frac: float = EDGE_MARGIN_FRAC,
) -> CropTrajectory:
    """Deadband+One-Euro center & asymmetric zoom, reset at scene cuts → per-sample marks.

    ``scene_cut_times`` are clip-relative seconds (already windowed by the caller).
    Each sample is independently TRACK (single face OR union of co-present faces) or
    GENERAL (faceless / edge-of-frame single face / true crowd). Both the center and
    the zoom/size are reset at each scene cut so neither glides across a shot edge.
    """
    deadband = deadband_frac * src_w
    euro = OneEuroFilter()
    held = src_w / 2.0
    zoom_h: float | None = None
    keyframes: list[CropKeyframe] = []

    for s in samples:
        at_cut = any(abs(s.t - cut) <= SNAP_EPS_S for cut in scene_cut_times)
        subject = _resolve_subject(s, src_w, src_h, edge_margin_frac)
        if at_cut:
            snap_to = subject.center_x if subject.center_x is not None else held
            euro.reset(snap_to, s.t)
            held = snap_to
            zoom_h = None  # hard zoom reset: no easing across the cut
        if subject.is_general or subject.box is None:
            keyframes.append(CropKeyframe(s.t, None, GENERAL_MARK, face=None))
            continue
        cx, held = _smooth_center(subject.center_x, held, euro, s.t, deadband)
        zoom_h = _ease_zoom(zoom_h, subject.box.h)
        keyframes.append(CropKeyframe(s.t, cx, TRACK_MARK, face=_scaled_box(subject.box, zoom_h)))

    return CropTrajectory(tuple(keyframes), src_w, src_h)
