"""Pure crop geometry + shared render value-types (P2 reframe; bbox-aware crop).

This module owns every shared frozen type the render leg passes around
(``FaceBox``, ``CropKeyframe``, ``CropTrajectory``, ``CropBox``) so that the
impure ``render.py`` and ``speaker_region.py`` depend only on leaf pure code —
and so ``engine.cascade`` (which imports ``..clipping``) never pulls a heavy
chain at import time. All math is integer-exact and fail-closed: a window can
only ever sit fully inside the source frame, on even pixel bounds (the H.264
chroma-subsampling invariant), or it raises.

Phase 1 makes the crop SUBJECT-AWARE: ``compute_crop_box`` takes the active
subject bounding box (one face, or the UNION of 2-3 co-present faces) and emits
a VARIABLE-SIZE 9:16 window that fully contains the padded subject — composed on
the upper third, never over-zoomed (a min-zoom clamp targets a ~30-45% face),
and widened (never sliced) when the subject is too wide to fit a 9:16 column.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

from .frontality import Landmarks, is_frontal
from .frontality import frontality as _frontality

TARGET_W: int = 1080
TARGET_H: int = 1920
TARGET_RATIO: float = TARGET_W / TARGET_H  # 0.5625 (width / height)

CROP_MODE: str = "CROP"
BLURPAD_MODE: str = "BLURPAD"
TRACK_MARK: str = "TRACK"
GENERAL_MARK: str = "GENERAL"

# Crop LAYOUTS — the geometry INSIDE a CROP_MODE box (never blur-pad). ``SINGLE`` is
# the classic one-window 9:16 fill-crop. ``STACK`` is the vertical split-screen: N
# per-speaker panels each cropped from the source and vstacked top→bottom into one
# 1080×1920 frame, used ONLY when two co-present heads are too far apart to share one
# undistorted 9:16 column. STACK is a NEW explicit CROP-family mode — NOT blur-pad.
SINGLE_LAYOUT: str = "SINGLE"
STACK_LAYOUT: str = "STACK"

# A vertical split holds at most this many panels (2 today: top/bottom). 3+ co-present
# heads are a true group shot kept as one wide union, never split.
MAX_STACK_PANELS: int = 2

# ── Subject-aware crop tuning (all fractions of the subject box / source) ─────
# Horizontal breathing room added to each side of the subject before fitting.
HORIZONTAL_PAD_FRAC: float = 0.12
# Vertical padding is ASYMMETRIC so the eyes/upper face land on the upper-third
# line: more space above the head than below the chin.
#
# MediaPipe's FaceBox TOP is the forehead/eyebrows — it does NOT include the
# hair/skull above. SKULL_PAD_FRAC first extends the top up to the hairline (≈
# half a face height above the detected forehead) so the WHOLE head is in frame;
# HEADROOM_PAD_FRAC is the breathing room ABOVE that skull line. The effective
# top padding the window must contain is therefore (SKULL + HEADROOM) * face.h.
SKULL_PAD_FRAC: float = 0.62  # forehead → hairline/skull top (whole head, not just face)
HEADROOM_PAD_FRAC: float = 0.45  # breathing room ABOVE the skull line (the larger share)
CHIN_PAD_FRAC: float = 0.22  # below the subject bottom (the smaller share)
# Min-zoom clamp: a single face should occupy at most this fraction of the crop
# height, so the crop is framed WIDE (head + shoulders + headroom), never punched
# in onto the head. Lower = wider framing / less zoom.
FACE_TARGET_HEIGHT_FRAC: float = 0.28
# Absolute floor: never crop a window shorter than this fraction of the source
# height (a hard cap on zoom-in regardless of how small the face is). Higher =
# more source context kept = less zoom.
MIN_CROP_HEIGHT_FRAC: float = 0.78
# Upper-third composition: the subject's vertical center sits this fraction down
# from the window top (< 0.5 → subject HIGH in frame, eyes near the upper third).
UPPER_THIRD_FRAC: float = 0.40


def _top_pad_frac() -> float:
    """Total top padding as a fraction of face height: skull extension + headroom.

    Single source of truth for the padded subject TOP (forehead → skull → breathing
    room), so :func:`_pad_subject` and :func:`_place_y` never drift apart.
    """
    return SKULL_PAD_FRAC + HEADROOM_PAD_FRAC


@dataclass(frozen=True)
class FaceBox:
    """A detected face in source pixels (top-left origin).

    ``landmarks`` carries YuNet's 5 facial points (right eye, left eye, nose, right
    mouth, left mouth) when the detector is YuNet, or ``None`` for MediaPipe boxes
    (no landmarks). It drives :attr:`frontality`, used to prefer a face FACING the
    camera over a larger turned/profile head.
    """

    x: float
    y: float
    w: float
    h: float
    score: float
    landmarks: Landmarks | None = None

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h

    @property
    def frontality(self) -> float | None:
        """Frontality in ``[0, 1]`` from the landmarks (1 = facing camera), or ``None``.

        ``None`` when the detector supplied no landmarks (MediaPipe) — an UNKNOWN
        pose, distinct from a known profile (low score). Selection code treats
        ``None`` as "no frontal signal" and falls back to the largest-face heuristic.
        """
        return _frontality(self.landmarks) if self.landmarks is not None else None


def union_box(faces: tuple[FaceBox, ...]) -> FaceBox | None:
    """The tight bounding box enclosing every face in ``faces`` (or ``None`` if empty).

    Used for the multi-person case: 2-3 co-present faces collapse into ONE subject
    box so the crop keeps EVERYONE in frame instead of center-cropping the gap
    between heads. The union carries the min detection ``score`` (most conservative).
    """
    if not faces:
        return None
    x0 = min(f.x for f in faces)
    y0 = min(f.y for f in faces)
    x1 = max(f.x + f.w for f in faces)
    y1 = max(f.y + f.h for f in faces)
    return FaceBox(x=x0, y=y0, w=x1 - x0, h=y1 - y0, score=min(f.score for f in faces))


@dataclass(frozen=True)
class CropKeyframe:
    """The chosen crop subject at one sampled instant (clip-relative seconds).

    ``face`` carries the FULL active-subject bounding box (a single face, or the
    UNION of co-present faces) — or ``None`` on a GENERAL/faceless sample. The crop
    math fits this box; ``center_x`` is its horizontal center (kept for the
    deadband/One-Euro center smoothing and the GENERAL median classification).

    ``panels`` is non-empty ONLY when this TRACK sample is a split-screen STACK: it
    holds the per-speaker faces (left→right) the render leg vstacks. ``face`` then
    still holds their union (used only for the run's median center/zoom bookkeeping).
    """

    t: float
    center_x: float | None
    mode: str  # TRACK_MARK | GENERAL_MARK
    face: FaceBox | None = None
    panels: tuple[FaceBox, ...] = ()  # non-empty ⇔ this TRACK sample is a split-screen STACK


@dataclass(frozen=True)
class CropTrajectory:
    """The full per-sample crop path for a clip + the source dimensions it was built on."""

    keyframes: tuple[CropKeyframe, ...]
    source_width: int
    source_height: int

    def dominant_center(self) -> float | None:
        """Median of the non-None TRACK centers; ``None`` when no TRACK keyframe exists."""
        tracks = [
            kf.center_x
            for kf in self.keyframes
            if kf.mode == TRACK_MARK and kf.center_x is not None
        ]
        return median(tracks) if tracks else None

    def is_general(self) -> bool:
        """GENERAL iff there is no usable TRACK center (single source of truth).

        Defined strictly as ``dominant_center() is None`` — GENERAL classification
        lives only in :func:`smoothing.build_trajectory`; this never re-derives it
        from a second heuristic.
        """
        return self.dominant_center() is None


@dataclass(frozen=True)
class CropBox:
    """A source-pixel crop window plus the render mode + layout it implies.

    ``CROP_MODE`` → ffmpeg ``crop=w:h:x:y`` then scale to the target. This is the
    ONLY mode the live render path ever produces: the vertical reframe ALWAYS fills
    the frame by cropping a 9:16 window (speaker-tracked or centered). ``BLURPAD_MODE``
    is a retired legacy value kept only so the fail-closed render guard can name it.

    ``layout`` refines a ``CROP_MODE`` box. ``SINGLE_LAYOUT`` (default) is the classic
    one-window crop: ``(x, y, w, h)`` is the window and ``panels`` is empty.
    ``STACK_LAYOUT`` is the split-screen: ``panels`` holds the per-speaker sub-crops
    (each a SINGLE box, EXACTLY ``target_w:(target_h/n)``) the render leg crops, scales,
    and vstacks; the outer ``(x, y, w, h)`` then bounds the union of the panels so the
    fail-closed in-frame guard still has a window to check.
    """

    x: int
    y: int
    w: int
    h: int
    mode: str
    layout: str = SINGLE_LAYOUT
    panels: tuple[CropBox, ...] = ()


def _even(v: int) -> int:
    """Round DOWN to the nearest even int (H.264 chroma-subsampling invariant)."""
    return v - (v % 2)


def _pad_subject(face: FaceBox) -> tuple[float, float, float, float]:
    """Subject box → padded ``(left, top, right, bottom)`` in source px (unclamped).

    Horizontal padding is symmetric; vertical is asymmetric (more headroom above
    than below) so the face composes on the upper third. The TOP pad includes the
    skull extension (MediaPipe's box starts at the forehead) PLUS breathing room, so
    the padded box encloses the WHOLE head with visible space above it.
    """
    h_pad = HORIZONTAL_PAD_FRAC * face.w
    return (
        face.x - h_pad,
        face.y - _top_pad_frac() * face.h,
        face.x + face.w + h_pad,
        face.y + face.h + CHIN_PAD_FRAC * face.h,
    )


def _target_crop_height(face: FaceBox, padded_h: float, src_h: int) -> float:
    """Crop height that contains the padded subject AND honours the min-zoom clamp.

    Widen (raise the height) past the tight fit when the tight window would zoom in
    too far — bounded by the source height. Three lower bounds, then capped:
      * the padded subject height (must fully contain it),
      * the face occupying at most ``FACE_TARGET_HEIGHT_FRAC`` of the window,
      * the absolute ``MIN_CROP_HEIGHT_FRAC`` floor of the source height.
    """
    by_face = face.h / FACE_TARGET_HEIGHT_FRAC
    floor = MIN_CROP_HEIGHT_FRAC * src_h
    return min(float(src_h), max(padded_h, by_face, floor))


def _ratio_window(
    padded_w: float, crop_h: float, src_w: int, src_h: int, ratio: float
) -> tuple[int, int]:
    """An EXACT-``ratio`` (w:h) crop window that contains the padded subject width.

    CRITICAL: the window is ALWAYS ``ratio`` so scaling it to the 9:16 target never
    DISTORTS the image. Start from the min-zoom ``crop_h``; if the padded subject is
    too WIDE for that 9:16 column, GROW THE HEIGHT (never just the width) so the
    wider window stays exactly ``ratio``. Then clamp inside the source, shrinking the
    binding dimension and re-deriving the other from ``ratio``. Returns even
    ``(crop_w, crop_h)`` (even-pixel rounding keeps it ``ratio`` within ~1px).
    """
    crop_w = crop_h * ratio
    if padded_w > crop_w:  # too wide for the column → grow HEIGHT to keep 9:16
        crop_w = padded_w
        crop_h = crop_w / ratio
    if crop_w > src_w:  # clamp width, shrink height to match the ratio
        crop_w = float(src_w)
        crop_h = crop_w / ratio
    if crop_h > src_h:  # clamp height, shrink width to match the ratio
        crop_h = float(src_h)
        crop_w = crop_h * ratio
    ch = min(_even(round(crop_h)), _even(src_h))
    cw = min(_even(round(ch * ratio)), _even(src_w))
    return cw, ch


def _centered_window(src_w: int, src_h: int, ratio: float) -> tuple[int, int]:
    """The max source-fit 9:16 ``(crop_w, crop_h)`` for a centered (faceless) crop."""
    crop_h = min(_even(src_h), _even(round(src_w / ratio)))
    crop_w = min(_even(round(crop_h * ratio)), _even(src_w))
    return crop_w, crop_h


def _subject_window(face: FaceBox, src_w: int, src_h: int, ratio: float) -> tuple[int, int]:
    """The variable-size EXACT-9:16 ``(crop_w, crop_h)`` containing the padded subject."""
    left, top, right, bottom = _pad_subject(face)
    crop_h = _target_crop_height(face, bottom - top, src_h)
    return _ratio_window(right - left, crop_h, src_w, src_h, ratio)


def _contain(desired: float, lo: float, hi: float) -> float:
    """Clamp ``desired`` into ``[lo, hi]`` when that interval is valid (lo ≤ hi).

    Used to keep a padded subject edge fully inside the window: ``lo`` keeps the
    far edge in, ``hi`` keeps the near edge in. If the window is smaller than the
    padded box on this axis (lo > hi) the constraint is unsatisfiable, so the
    caller's framing preference is kept instead (no clamp).
    """
    return min(max(desired, lo), hi) if lo <= hi else desired


def _place_x(center_x: float | None, crop_w: int, src_w: int, face: FaceBox | None = None) -> int:
    """Even, in-range top-left x: centered on the subject, kept containing its width."""
    if center_x is None:
        desired = (src_w - crop_w) / 2.0
    else:
        desired = center_x - crop_w / 2.0
        if face is not None:
            pad = HORIZONTAL_PAD_FRAC * face.w
            desired = _contain(desired, (face.x + face.w + pad) - crop_w, face.x - pad)
    return _even(max(0, min(int(round(desired)), src_w - crop_w)))


def _place_y(face: FaceBox | None, crop_h: int, src_h: int) -> int:
    """Even, in-range top-left y placing the subject on the upper third (or top for none).

    The subject's vertical center is anchored ``UPPER_THIRD_FRAC`` down the window
    (eyes near the upper-third line), THEN constrained so the padded head/chin stay
    fully inside the window (no cut-off top of head), then clamped in-frame.
    Faceless → top (y=0).
    """
    if face is None:
        return 0
    desired = face.center_y - UPPER_THIRD_FRAC * crop_h
    padded_top = face.y - _top_pad_frac() * face.h
    padded_bottom = face.y + face.h + CHIN_PAD_FRAC * face.h
    desired = _contain(desired, padded_bottom - crop_h, padded_top)
    return _even(max(0, min(int(round(desired)), src_h - crop_h)))


def compute_crop_box(
    src_w: int,
    src_h: int,
    center_x: float | None,
    *,
    face: FaceBox | None = None,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
) -> CropBox:
    """Map an active subject to a variable-size 9:16 crop window (source px).

    ``face`` is the active-SUBJECT bounding box — one face, or the UNION of 2-3
    co-present faces (so a multi-person shot keeps everyone). When ``face`` is given
    the window is SIZED to contain the padded subject (upper-third composition,
    min-zoom clamped, widened-not-sliced when too wide); when ``face is None`` the
    crop is the centered max-fit 9:16 column (faceless GENERAL fallback).

    ALWAYS returns a ``CROP_MODE`` box — the vertical reframe ALWAYS fills the frame
    (founder mandate: never blur-pad). Fail-closed: non-positive source dims raise;
    the final window is forced even on every bound and re-checked to be fully
    in-frame with positive area, or it raises.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"source dims must be positive, got {src_w}x{src_h}")

    ratio = target_w / target_h
    if face is None:
        crop_w, crop_h = _centered_window(src_w, src_h, ratio)
    else:
        crop_w, crop_h = _subject_window(face, src_w, src_h, ratio)

    x = _place_x(center_x, crop_w, src_w, face=face)
    y = _place_y(face, crop_h, src_h)

    if crop_w <= 0 or crop_h <= 0 or x < 0 or y < 0 or x + crop_w > src_w or y + crop_h > src_h:
        raise ValueError(f"crop window {crop_w}x{crop_h}+{x}+{y} escapes source {src_w}x{src_h}")
    return CropBox(x=x, y=y, w=crop_w, h=crop_h, mode=CROP_MODE)


def subject_fits(
    face: FaceBox, src_w: int, src_h: int, *, target_w: int = TARGET_W, target_h: int = TARGET_H
) -> bool:
    """True if the padded subject fits an UNDISTORTED 9:16 crop (no stretch).

    The widest a 9:16 window can ever be is ``min(src_w, src_h * ratio)`` (a full-
    height column, or the whole frame on a portrait source). If the padded subject
    is wider than that, a single 9:16 crop CANNOT contain it without distorting —
    so the caller must follow ONE face (or split-screen) instead of unioning the
    gap between far-apart heads.
    """
    ratio = target_w / target_h
    padded_w = face.w * (1.0 + 2.0 * HORIZONTAL_PAD_FRAC)
    return padded_w <= min(float(src_w), src_h * ratio)


def union_contains_in_widest(
    face: FaceBox, src_w: int, src_h: int, *, target_w: int = TARGET_W, target_h: int = TARGET_H
) -> bool:
    """True if the RAW (unpadded) union fits the WIDEST source-fit 9:16 crop.

    The two-person fallback: when a TIGHT padded union does not fit (``subject_fits``
    is False) but BOTH heads still sit inside the widest 9:16 column the source can
    host, we should still show EVERYONE (both smaller) rather than punch into one
    head. This drops the breathing padding and asks only whether the bare union width
    is contained by ``min(src_w, src_h*ratio)`` — strictly wider than ``subject_fits``.
    """
    ratio = target_w / target_h
    return face.w <= min(float(src_w), src_h * ratio)


def _panel_box(face: FaceBox, src_w: int, src_h: int, panel_ratio: float) -> CropBox:
    """One STACK panel: an EXACT ``panel_ratio`` (w:h) source window framing ``face``.

    Same exact-ratio discipline as the main crop — the window is sized by :func:`_subject_window`
    (which GROWS HEIGHT, never stretches width, to keep the panel ratio when the padded
    face is too wide) and placed with the shared upper-third / containment helpers. The
    render leg later scales this window to ``target_w × (target_h/n)``; because the window
    is ALREADY ``panel_ratio == target_w / (target_h/n)``, that scale never distorts.
    Fail-closed: a window that escaped the source raises rather than ship a bad panel.
    """
    crop_w, crop_h = _subject_window(face, src_w, src_h, panel_ratio)
    x = _place_x(face.center_x, crop_w, src_w, face=face)
    y = _place_y(face, crop_h, src_h)
    if crop_w <= 0 or crop_h <= 0 or x < 0 or y < 0 or x + crop_w > src_w or y + crop_h > src_h:
        raise ValueError(f"STACK panel {crop_w}x{crop_h}+{x}+{y} escapes source {src_w}x{src_h}")
    return CropBox(x=x, y=y, w=crop_w, h=crop_h, mode=CROP_MODE)


def _panel_ratio(target_w: int, target_h: int, n: int) -> float:
    """The aspect ratio of one of ``n`` equal vstacked tiles (``target_w : target_h/n``).

    Fail-closed: ``target_h`` must split into ``n`` EVEN tiles that re-sum to ``target_h``
    (the H.264 chroma-subsampling invariant on every tile, and an exact vstack back to
    the delivery height), or it raises.
    """
    tile_h = _even(target_h // n)
    if tile_h <= 0 or tile_h * n != target_h:
        raise ValueError(f"target height {target_h} not evenly stackable into {n} tiles")
    return target_w / tile_h


def compute_stack_box(
    faces: tuple[FaceBox, ...],
    src_w: int,
    src_h: int,
    *,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
) -> CropBox:
    """Split-screen STACK: each co-present face → its own panel, vstacked top→bottom.

    Each of the ``n`` panels (``n == len(faces)``, 2..``MAX_STACK_PANELS``) is an EXACT
    ``target_w:(target_h/n)`` source window framing one face (NO stretch — height grows
    to hold the ratio). Faces are ordered LEFT→RIGHT so the on-screen stack mirrors the
    scene. The returned outer box bounds the union of the panels (a real, in-frame
    window for the fail-closed guard); ``layout`` is ``STACK_LAYOUT`` and ``panels``
    carries the sub-crops. Fail-closed: bad source dims / wrong face count / a panel
    escaping the source all raise.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"source dims must be positive, got {src_w}x{src_h}")
    n = len(faces)
    if not (2 <= n <= MAX_STACK_PANELS):
        raise ValueError(f"STACK needs 2..{MAX_STACK_PANELS} faces, got {n}")

    panel_ratio = _panel_ratio(target_w, target_h, n)
    ordered = tuple(sorted(faces, key=lambda f: f.center_x))
    panels = tuple(_panel_box(face, src_w, src_h, panel_ratio) for face in ordered)

    bx = min(p.x for p in panels)
    by = min(p.y for p in panels)
    bw = _even(max(p.x + p.w for p in panels) - bx)
    bh = _even(max(p.y + p.h for p in panels) - by)
    return CropBox(x=bx, y=by, w=bw, h=bh, mode=CROP_MODE, layout=STACK_LAYOUT, panels=panels)


def should_stack(
    faces: tuple[FaceBox, ...],
    src_w: int,
    src_h: int,
    *,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
) -> bool:
    """The hard split gate: True ⇔ split these co-present faces into a STACK. PURE.

    Returns True ONLY when EXACTLY two faces are co-present in the SAME source frame,
    BOTH face the camera (reasonably frontal), and they CANNOT share one undistorted
    9:16 column (``subject_fits``/``union_contains_in_widest`` on their union both fail
    — the far-apart case ``smoothing`` would otherwise punch into the dominant head).
    Never splits a single face, a group of more than two, any pair that still fits one
    column, or a pair where a head is turned away (a profile reads badly in its own
    tile). Every condition is structural, so the decision is deterministic.
    """
    if len(faces) != MAX_STACK_PANELS:
        return False
    if not all(is_frontal(f.frontality) for f in faces):
        return False
    # Two real faces ⇒ ``union_box`` is never None; ``or faces[0]`` satisfies the
    # type-checker without an unreachable branch the coverage gate would flag.
    union = union_box(faces) or faces[0]
    fits_one_column = subject_fits(
        union, src_w, src_h, target_w=target_w, target_h=target_h
    ) or union_contains_in_widest(union, src_w, src_h, target_w=target_w, target_h=target_h)
    return not fits_one_column


def clip_filename(rank: int) -> str:
    """Deterministic zero-padded clip filename for a rank (0 = best)."""
    return f"clip_{rank:02d}.mp4"


def round_duration(start: float, end: float) -> float:
    """Clip duration in seconds, rounded to 3 decimals."""
    return round(end - start, 3)
