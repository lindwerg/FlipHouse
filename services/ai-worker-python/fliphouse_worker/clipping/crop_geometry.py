"""Pure crop geometry + shared render value-types (P2-2.4 render).

This module owns every shared frozen type the render leg passes around
(``FaceBox``, ``CropKeyframe``, ``CropTrajectory``, ``CropBox``) so that the
impure ``render.py`` and ``speaker_region.py`` depend only on leaf pure code —
and so ``engine.cascade`` (which imports ``..clipping``) never pulls a heavy
chain at import time. All math is integer-exact and fail-closed: a window can
only ever sit fully inside the source frame, on even pixel bounds (the H.264
chroma-subsampling invariant), or it raises.
"""

from __future__ import annotations

from dataclasses import dataclass
from statistics import median

TARGET_W: int = 1080
TARGET_H: int = 1920
TARGET_RATIO: float = TARGET_W / TARGET_H  # 0.5625

CROP_MODE: str = "CROP"
BLURPAD_MODE: str = "BLURPAD"
TRACK_MARK: str = "TRACK"
GENERAL_MARK: str = "GENERAL"


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
    def area(self) -> float:
        return self.w * self.h


@dataclass(frozen=True)
class CropKeyframe:
    """The chosen crop center at one sampled instant (clip-relative seconds)."""

    t: float
    center_x: float | None
    mode: str  # TRACK_MARK | GENERAL_MARK


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


def compute_crop_box(
    src_w: int,
    src_h: int,
    center_x: float | None,
    *,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
) -> CropBox:
    """Map a subject center (source px, or ``None`` = centered) to a crop window.

    ALWAYS returns a ``CROP_MODE`` box — the vertical reframe ALWAYS fills the frame
    by cropping a 9:16 window (founder mandate: never blur-pad). Fail-closed, in this
    exact order:
      1. ``src_w <= 0`` or ``src_h <= 0`` → ``ValueError``.
      2. ``crop_w`` = the full-height 9:16 column width, floored to even.
      3. clamp ``crop_w`` to ``src_w`` (a source narrower than 9:16 — e.g. a genuinely
         vertical clip — crops its full width, which then scales to fill the frame).
      4. desired ``x`` from the center (or centered when ``center_x is None``).
      5. clamp ``x`` into ``[0, src_w - crop_w]`` FIRST.
      6. floor ``x`` to even (still in range, since the range start is >= 0).
      7. post-condition guard: any out-of-frame window → ``ValueError``.
    """
    if src_w <= 0 or src_h <= 0:
        raise ValueError(f"source dims must be positive, got {src_w}x{src_h}")

    crop_w = _even(round(src_h * target_w / target_h))
    crop_w = min(crop_w, _even(src_w))  # narrower-than-9:16 source → crop full width

    if center_x is None:
        desired = (src_w - crop_w) / 2.0
    else:
        desired = center_x - crop_w / 2.0

    x = max(0, min(int(round(desired)), src_w - crop_w))
    x = _even(x)
    crop_h = src_h

    if x < 0 or x + crop_w > src_w or crop_h > src_h:  # pragma: no cover - guarded by steps 2-6
        raise ValueError(f"crop window {crop_w}x{crop_h}+{x} escapes source {src_w}x{src_h}")
    return CropBox(x=x, y=0, w=crop_w, h=crop_h, mode=CROP_MODE)


def clip_filename(rank: int) -> str:
    """Deterministic zero-padded clip filename for a rank (0 = best)."""
    return f"clip_{rank:02d}.mp4"


def round_duration(start: float, end: float) -> float:
    """Clip duration in seconds, rounded to 3 decimals."""
    return round(end - start, 3)
