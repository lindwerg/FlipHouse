"""Render segmentation (P2 reframe).

A clip's render is split into an ordered list of :class:`RenderSegment`s — each a
contiguous time interval with ONE :class:`CropBox` — which ``render.py`` renders
independently and concatenates.

Founder mandate: the vertical reframe NEVER speaker-crops/zooms. The full source
frame is ALWAYS shown (blur-pad fit). So every clip is exactly ONE full-frame
blur-pad segment today; the multi-segment / concat machinery in ``render.py``
stays in place for the Phase-3 reframe seam but is not exercised by the live path.
PURE.
"""

from __future__ import annotations

from dataclasses import dataclass

from .crop_geometry import BLURPAD_MODE, CropBox, CropTrajectory


@dataclass(frozen=True)
class RenderSegment:
    """A contiguous clip-relative interval rendered with one crop window."""

    start_s: float  # clip-relative seconds (0.0 = clip start)
    end_s: float
    box: CropBox

    @property
    def span(self) -> float:
        return self.end_s - self.start_s


def build_blurpad_segments(
    traj: CropTrajectory,
    *,
    clip_duration: float,
) -> tuple[RenderSegment, ...]:
    """:class:`CropTrajectory` → exactly ONE full-frame blur-pad segment.

    The reframe always shows the FULL source frame (founder mandate: never
    speaker-crop/zoom), so the trajectory's per-sample face track is intentionally
    ignored — only the source dimensions are carried into the (geometry-ignoring)
    blur-pad box. The segment covers ``[0, clip_duration]``. PURE.
    """
    full_frame = CropBox(0, 0, traj.source_width, traj.source_height, BLURPAD_MODE)
    return (RenderSegment(0.0, clip_duration, full_frame),)
