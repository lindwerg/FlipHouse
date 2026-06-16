"""Pure crop-trajectory builder (P2-2.4 render).

Turns a sequence of per-frame face-center samples into a smoothed
:class:`CropTrajectory`: a deadband holds the window still under small motion,
the One-Euro filter follows larger moves, and the filter is reset hard at each
precomputed scene cut so the crop never glides across a shot boundary. A
group-shot (more than ``general_face_max`` average faces) or a faceless clip is
forced to GENERAL so a 2-shot is never wrong-cropped onto one head.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from statistics import mean

from .crop_geometry import GENERAL_MARK, TRACK_MARK, CropKeyframe, CropTrajectory
from .one_euro import OneEuroFilter

DEADBAND_FRAC: float = 0.10
GENERAL_FACE_MAX: float = 1.2
SNAP_EPS_S: float = 0.30


@dataclass(frozen=True)
class RawSample:
    """One sampled instant: the chosen face center (or None) and how many faces were seen."""

    t: float
    center_x: float | None
    face_count: int


def build_trajectory(
    samples: Sequence[RawSample],
    scene_cut_times: Sequence[float],
    src_w: int,
    src_h: int,
    *,
    deadband_frac: float = DEADBAND_FRAC,
    general_face_max: float = GENERAL_FACE_MAX,
) -> CropTrajectory:
    """Deadband-gate → One-Euro smooth → reset at each scene cut → TRACK/GENERAL per sample.

    ``scene_cut_times`` are clip-relative seconds (already windowed by the caller).
    Group-shot override: when the mean face count over face-bearing samples exceeds
    ``general_face_max`` — or no sample had a face — every keyframe becomes GENERAL.
    """
    deadband = deadband_frac * src_w
    euro = OneEuroFilter()
    held = src_w / 2.0
    keyframes: list[CropKeyframe] = []
    face_counts: list[int] = []

    for s in samples:
        if any(abs(s.t - cut) <= SNAP_EPS_S for cut in scene_cut_times):
            snap_to = s.center_x if s.center_x is not None else held
            euro.reset(snap_to, s.t)
            held = snap_to
        if s.center_x is None:
            keyframes.append(CropKeyframe(s.t, None, GENERAL_MARK))
            continue
        face_counts.append(s.face_count)
        if abs(s.center_x - held) < deadband:
            cx = held
        else:
            cx = euro.filter(s.center_x, s.t)
            held = cx
        keyframes.append(CropKeyframe(s.t, cx, TRACK_MARK))

    avg_faces = mean(face_counts) if face_counts else 0.0
    if avg_faces == 0.0 or avg_faces > general_face_max:
        keyframes = [CropKeyframe(kf.t, None, GENERAL_MARK) for kf in keyframes]
    return CropTrajectory(tuple(keyframes), src_w, src_h)
