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

TARGET_W: int = 1080
TARGET_H: int = 1920
TARGET_RATIO: float = TARGET_W / TARGET_H  # 0.5625 (width / height)

CROP_MODE: str = "CROP"
BLURPAD_MODE: str = "BLURPAD"
TRACK_MARK: str = "TRACK"
GENERAL_MARK: str = "GENERAL"

# ── Subject-aware crop tuning (all fractions of the subject box / source) ─────
# Horizontal breathing room added to each side of the subject before fitting.
HORIZONTAL_PAD_FRAC: float = 0.12
# Vertical padding is ASYMMETRIC so the eyes/upper face land on the upper-third
# line: more space above the head than below the chin.
HEADROOM_PAD_FRAC: float = 0.55  # above the subject top (the larger share)
CHIN_PAD_FRAC: float = 0.22  # below the subject bottom (the smaller share)
# Min-zoom clamp: a single face should occupy at most this fraction of the crop
# height (≈30-45% face), so the crop never zooms in onto the head.
FACE_TARGET_HEIGHT_FRAC: float = 0.42
# Absolute floor: never crop a window shorter than this fraction of the source
# height (a hard cap on zoom-in regardless of how small the face is).
MIN_CROP_HEIGHT_FRAC: float = 0.55
# Upper-third composition: the subject's vertical center sits this fraction down
# from the window top (< 0.5 → subject HIGH in frame, eyes near the upper third).
UPPER_THIRD_FRAC: float = 0.40


@dataclass(frozen=True)
class FaceBox:
    """A detected face in source pixels (top-left origin)."""

    x: float
    y: float
    w: float
    h: float
    score: float

    @property
    def center_x(self) -> float:
        return self.x + self.w / 2.0

    @property
    def center_y(self) -> float:
        return self.y + self.h / 2.0

    @property
    def area(self) -> float:
        return self.w * self.h


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
    """

    t: float
    center_x: float | None
    mode: str  # TRACK_MARK | GENERAL_MARK
    face: FaceBox | None = None


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
    """A source-pixel crop window plus the render mode it implies.

    ``CROP_MODE`` → ffmpeg ``crop=w:h:x:y`` then scale to the target. This is the
    ONLY mode the live render path ever produces: the vertical reframe ALWAYS fills
    the frame by cropping a 9:16 window (speaker-tracked or centered). ``BLURPAD_MODE``
    is a retired legacy value kept only so the fail-closed render guard can name it.
    """

    x: int
    y: int
    w: int
    h: int
    mode: str


def _even(v: int) -> int:
    """Round DOWN to the nearest even int (H.264 chroma-subsampling invariant)."""
    return v - (v % 2)


def _pad_subject(face: FaceBox) -> tuple[float, float, float, float]:
    """Subject box → padded ``(left, top, right, bottom)`` in source px (unclamped).

    Horizontal padding is symmetric; vertical is asymmetric (more headroom above
    than below) so the face composes on the upper third.
    """
    h_pad = HORIZONTAL_PAD_FRAC * face.w
    return (
        face.x - h_pad,
        face.y - HEADROOM_PAD_FRAC * face.h,
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


def _fit_916_window(padded_w: float, crop_h: float, src_w: int, ratio: float) -> float:
    """9:16 crop WIDTH for a given height that still contains the padded width.

    Normally ``crop_h * ratio``. When the padded subject is too WIDE to fit that
    column (far-apart faces), widen to the max source-fit 9:16 width and accept —
    we never slice a face (true split-screen is a later increment).
    """
    column = crop_h * ratio
    if padded_w <= column:
        return column
    return min(float(src_w), padded_w)


def _centered_window(src_w: int, src_h: int, ratio: float) -> tuple[int, int]:
    """The max source-fit 9:16 ``(crop_w, crop_h)`` for a centered (faceless) crop."""
    crop_w = _even(round(src_h * ratio))
    crop_w = min(crop_w, _even(src_w))
    return crop_w, src_h


def _subject_window(face: FaceBox, src_w: int, src_h: int, ratio: float) -> tuple[int, int]:
    """The variable-size 9:16 ``(crop_w, crop_h)`` containing the padded subject."""
    left, top, right, bottom = _pad_subject(face)
    padded_w = right - left
    padded_h = bottom - top
    crop_h = _target_crop_height(face, padded_h, src_h)
    crop_w = _fit_916_window(padded_w, crop_h, src_w, ratio)
    return _even(round(min(crop_w, float(src_w)))), _even(round(min(crop_h, float(src_h))))


def _place_x(center_x: float | None, crop_w: int, src_w: int) -> int:
    """Even, in-range top-left x: centered on the subject (or frame-centered)."""
    if center_x is None:
        desired = (src_w - crop_w) / 2.0
    else:
        desired = center_x - crop_w / 2.0
    return _even(max(0, min(int(round(desired)), src_w - crop_w)))


def _place_y(face: FaceBox | None, crop_h: int, src_h: int) -> int:
    """Even, in-range top-left y placing the subject on the upper third (or top for none).

    The subject's vertical center is anchored ``UPPER_THIRD_FRAC`` down the window
    (subject high in frame, eyes near the upper-third line), then clamped in-frame.
    Faceless → top (y=0).
    """
    if face is None:
        return 0
    desired = face.center_y - UPPER_THIRD_FRAC * crop_h
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

    x = _place_x(center_x, crop_w, src_w)
    y = _place_y(face, crop_h, src_h)

    if crop_w <= 0 or crop_h <= 0 or x < 0 or y < 0 or x + crop_w > src_w or y + crop_h > src_h:
        raise ValueError(f"crop window {crop_w}x{crop_h}+{x}+{y} escapes source {src_w}x{src_h}")
    return CropBox(x=x, y=y, w=crop_w, h=crop_h, mode=CROP_MODE)


def clip_filename(rank: int) -> str:
    """Deterministic zero-padded clip filename for a rank (0 = best)."""
    return f"clip_{rank:02d}.mp4"


def round_duration(start: float, end: float) -> float:
    """Clip duration in seconds, rounded to 3 decimals."""
    return round(end - start, 3)
