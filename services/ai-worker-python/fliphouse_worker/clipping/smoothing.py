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

from .active_speaker import pick_active_speaker
from .crop_geometry import (
    CONTEXT_CONTAIN_MARK,
    GENERAL_MARK,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    needs_context,
    should_stack,
    subject_fits,
    union_box,
    union_contains_in_widest,
)
from .frontality import is_frontal
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
    """The resolved per-sample crop subject: a box + its center, or GENERAL (no box).

    ``panels`` is non-empty ONLY for a split-screen STACK sample — the per-speaker faces
    (left→right) the render leg vstacks. ``box`` then holds their union (center/zoom only).

    ``contain`` is True when a real subject WAS resolved but a tight 9:16 column would
    SLICE meaningful side context (``needs_context`` fired) — a cinematic WIDE shot. The
    keyframe then carries the CONTEXT-CONTAIN intent so the run renders as the full-frame
    CONTAIN graph (founder: "сбоку не входит") instead of a 608px punch-in. ``box``/
    ``center_x`` stay populated (the subject is known) but are not used for sizing.
    """

    box: FaceBox | None
    center_x: float | None
    is_general: bool
    panels: tuple[FaceBox, ...] = ()
    contain: bool = False


def _near_edge(center_x: float, src_w: int, edge_margin_frac: float) -> bool:
    """True when the active face center is within ``edge_margin_frac`` of either side."""
    margin = edge_margin_frac * src_w
    return center_x < margin or center_x > src_w - margin


def _pick_dominant(faces: tuple[FaceBox, ...]) -> FaceBox | None:
    """The single face to punch into when both can't be kept: speaker-first, then frontal.

    REFRAME Phase 4: when the GPU LR-ASD lane marks one face as the active SPEAKER,
    punch into THAT face regardless of size or pose — this is the profile/who-to-follow
    fix (follow whoever talks, not the larger silent/turned head). Absent an ASD
    speaker we keep founder complaint 3's rule: never punch into a head turned AWAY,
    so prefer the FRONTAL face (even if smaller); only among equally-(non-)frontal
    faces does the LARGEST win. With no faces at all, ``None``.
    """
    if not faces:
        return None
    speaker = pick_active_speaker(faces)
    if speaker is not None:
        return speaker
    frontal = [f for f in faces if is_frontal(f.frontality)]
    pool = frontal if frontal else list(faces)
    return max(pool, key=lambda f: f.area)


def _all_profile(faces: tuple[FaceBox, ...]) -> bool:
    """True when ≥2 faces are present, NONE faces the camera, AND none is an ASD speaker.

    A landmark-bearing (YuNet) frame in which every head is turned/profile and the
    GPU ASD lane (when present) found no talker. Nobody is a clear speaker-to-camera,
    so punching into one profile would just pick a side/back-of-head — we keep the
    WIDER 2-shot framing instead. Requires real frontality signal (a known low score),
    not the ``None`` of a landmark-less MediaPipe box, so the MediaPipe fallback path
    is never forced wide. If ANY face is an ASD speaker we do NOT stay wide — the
    caller's :func:`_pick_dominant` punches into the talker instead.
    """
    if len(faces) < 2:
        return False
    if pick_active_speaker(faces) is not None:
        return False
    return all(f.frontality is not None and not is_frontal(f.frontality) for f in faces)


def _resolve_subject(s: RawSample, src_w: int, src_h: int, edge_margin_frac: float) -> _Subject:
    """Per-sample subject: GENERAL, single active face, or the union of co-present faces.

    Co-present 2-3 faces collapse into ONE union box (everyone kept) whenever a single
    undistorted 9:16 crop can hold both — either a TIGHT padded fit or, failing that,
    the WIDEST source-fit window. When even the widest 9:16 cannot contain both (truly
    far apart) the subject becomes a SINGLE face: the FRONTAL one if exactly one head
    faces the camera, else (only-profiles, nobody facing camera) we stay on the WIDER
    2-shot union rather than punch into a side/back-of-head. A single active face near
    a frame edge degrades to GENERAL (subject leaving into b-roll). A true crowd
    (> ``CO_PRESENT_MAX`` faces) or a faceless frame is GENERAL.
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
        if u is not None and (
            subject_fits(u, src_w, src_h) or union_contains_in_widest(u, src_w, src_h)
        ):
            return _Subject(box=u, center_x=u.center_x, is_general=False)
        # Too far apart for one 9:16. If BOTH heads face the camera, give each its OWN
        # panel in a vertical split-screen STACK (both speakers kept, full-size, no
        # distortion) instead of punching into the dominant one. Hard-gated on exactly
        # two co-present same-frame frontal faces by ``should_stack``.
        if u is not None and should_stack(s.faces, src_w, src_h):
            return _Subject(box=u, center_x=u.center_x, is_general=False, panels=s.faces)
        # Too far apart for one 9:16 AND nobody faces the camera (only profiles): the wide
        # union itself exceeds the widest 9:16 column, so a single SINGLE crop would slice
        # one head out. Keep the WHOLE scene via CONTEXT-CONTAIN (founder: "сбоку не входит")
        # — the full-frame fit keeps both profiles in rather than punching a side/back-of-head.
        if u is not None and _all_profile(s.faces):
            return _Subject(box=u, center_x=u.center_x, is_general=False, contain=True)
        # Otherwise punch into the single best face (frontal-first, then largest) — UNLESS
        # that lone dominant head sits in a wide meaningful scene, in which case keep the
        # scene via CONTEXT-CONTAIN rather than a 608px column.
        dom = _pick_dominant(s.faces)
        if dom is None:
            return _Subject(box=None, center_x=None, is_general=True)
        contain = needs_context(dom, src_w, src_h)
        return _Subject(box=dom, center_x=dom.center_x, is_general=False, contain=contain)
    if _near_edge(s.center_x, src_w, edge_margin_frac):
        return _Subject(box=None, center_x=None, is_general=True)
    # A lone subject in a CINEMATIC WIDE shot (small / off-center such that a tight 9:16
    # column would discard salient horizontal context) escapes to CONTEXT-CONTAIN — the
    # founder-pleasing default that keeps the scene in. A genuine centered close-up does
    # NOT fire ``needs_context`` and still FILLs via the SINGLE speaker crop.
    if s.face is not None and needs_context(s.face, src_w, src_h):
        return _Subject(box=s.face, center_x=s.center_x, is_general=False, contain=True)
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
        if subject.contain:
            # A real subject was resolved, but a tight 9:16 column would slice the scene
            # (founder: "сбоку не входит"). Emit a CONTEXT-CONTAIN keyframe: it renders as
            # the full-frame CONTAIN graph (no speaker column, no center/zoom dependence),
            # so it carries NO face/center — identical mechanics to GENERAL but a distinct
            # mark so it is NEVER counted as a TRACK speaker center.
            keyframes.append(CropKeyframe(s.t, None, CONTEXT_CONTAIN_MARK, face=None))
            continue
        cx, held = _smooth_center(subject.center_x, held, euro, s.t, deadband)
        zoom_h = _ease_zoom(zoom_h, subject.box.h)
        keyframes.append(
            CropKeyframe(
                s.t,
                cx,
                TRACK_MARK,
                face=_scaled_box(subject.box, zoom_h),
                panels=subject.panels,
            )
        )

    return CropTrajectory(tuple(keyframes), src_w, src_h)
