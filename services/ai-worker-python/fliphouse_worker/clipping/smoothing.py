"""Pure crop-trajectory builder (P2-2.4 render; P2 dynamic-reframe steps 3+4).

Turns per-sample face-center samples into a smoothed :class:`CropTrajectory`: a
deadband holds the window still under small motion, the One-Euro filter follows
larger moves, and the filter is reset hard at each precomputed scene cut so the
crop never glides across a shot boundary. The TRACK-vs-GENERAL decision is made
PER SAMPLE (not once for the whole clip), so a clip that alternates between a
talking head and full-frame b-roll yields a time-varying trajectory the segment
builder can split. A sample is GENERAL when it has no face, is a group shot
(more than ``general_face_max`` faces), or the active face sits within
``edge_margin_frac`` of a frame edge (a subject leaving frame into b-roll →
show the whole frame instead of a hard side-crop).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from .crop_geometry import GENERAL_MARK, TRACK_MARK, CropKeyframe, CropTrajectory, FaceBox
from .one_euro import OneEuroFilter

DEADBAND_FRAC: float = 0.10
GENERAL_FACE_MAX: float = 1.2
SNAP_EPS_S: float = 0.30
EDGE_MARGIN_FRAC: float = 0.10  # active face this close to a frame edge → show whole frame


@dataclass(frozen=True)
class RawSample:
    """One sampled instant: the chosen face center (or None) and how many faces were seen.

    ``face`` is the FULL bounding box of the active face (``None`` when no face was
    chosen). It rides alongside ``center_x`` so the trajectory can later fit the head
    box rather than over-zoom from the center alone — Phase 0 only threads it through.
    """

    t: float
    center_x: float | None
    face_count: int
    face: FaceBox | None = None


def _near_edge(center_x: float, src_w: int, edge_margin_frac: float) -> bool:
    """True when the active face center is within ``edge_margin_frac`` of either side."""
    margin = edge_margin_frac * src_w
    return center_x < margin or center_x > src_w - margin


def build_trajectory(
    samples: Sequence[RawSample],
    scene_cut_times: Sequence[float],
    src_w: int,
    src_h: int,
    *,
    deadband_frac: float = DEADBAND_FRAC,
    general_face_max: float = GENERAL_FACE_MAX,
    edge_margin_frac: float = EDGE_MARGIN_FRAC,
) -> CropTrajectory:
    """Deadband-gate → One-Euro smooth → reset at each scene cut → per-sample TRACK/GENERAL.

    ``scene_cut_times`` are clip-relative seconds (already windowed by the caller).
    Each sample is independently TRACK or GENERAL — a faceless / group-shot /
    edge-of-frame sample becomes GENERAL on its own, so the downstream segment
    builder sees a genuinely time-varying mode timeline (no clip-global force).
    """
    deadband = deadband_frac * src_w
    euro = OneEuroFilter()
    held = src_w / 2.0
    keyframes: list[CropKeyframe] = []

    for s in samples:
        if any(abs(s.t - cut) <= SNAP_EPS_S for cut in scene_cut_times):
            snap_to = s.center_x if s.center_x is not None else held
            euro.reset(snap_to, s.t)
            held = snap_to
        if (
            s.center_x is None
            or s.face_count > round(general_face_max)
            or _near_edge(s.center_x, src_w, edge_margin_frac)
        ):
            keyframes.append(CropKeyframe(s.t, None, GENERAL_MARK, face=None))
            continue
        if abs(s.center_x - held) < deadband:
            cx = held
        else:
            cx = euro.filter(s.center_x, s.t)
            held = cx
        keyframes.append(CropKeyframe(s.t, cx, TRACK_MARK, face=s.face))

    return CropTrajectory(tuple(keyframes), src_w, src_h)
