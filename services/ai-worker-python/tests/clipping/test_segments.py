"""segments — full-frame blur-pad segment builder (founder mandate: never crop)."""

from fliphouse_worker.clipping.crop_geometry import (
    BLURPAD_MODE,
    GENERAL_MARK,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
)
from fliphouse_worker.clipping.segments import RenderSegment, build_blurpad_segments


def _kf(t: float, mode: str, cx: float | None = 960.0) -> CropKeyframe:
    return CropKeyframe(t, cx if mode == TRACK_MARK else None, mode)


def _track(n: int, *, cx: float = 960.0, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, TRACK_MARK, cx) for i in range(n)]


def _general(n: int, *, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, GENERAL_MARK) for i in range(n)]


def _traj(keyframes: list[CropKeyframe], *, w: int = 1920, h: int = 1080) -> CropTrajectory:
    return CropTrajectory(tuple(keyframes), w, h)


# ── build_blurpad_segments ─────────────────────────────────────────────────


def test_track_trajectory_is_single_blurpad_segment():
    # The face track is intentionally IGNORED — the full frame is always shown.
    segs = build_blurpad_segments(_traj(_track(4, cx=960.0)), clip_duration=6.0)
    assert len(segs) == 1
    assert segs[0].box.mode == BLURPAD_MODE
    assert (segs[0].start_s, segs[0].end_s) == (0.0, 6.0)


def test_general_trajectory_is_single_blurpad_segment():
    segs = build_blurpad_segments(_traj(_general(4)), clip_duration=6.0)
    assert len(segs) == 1 and segs[0].box.mode == BLURPAD_MODE


def test_no_keyframes_yields_single_blurpad_segment():
    segs = build_blurpad_segments(_traj([]), clip_duration=8.0)
    assert segs == (RenderSegment(0.0, 8.0, segs[0].box),)
    assert segs[0].box.mode == BLURPAD_MODE


def test_mixed_trajectory_never_produces_a_crop_segment():
    kfs = _track(6, cx=960.0) + _general(3, start_idx=6) + _track(3, cx=500.0, start_idx=9)
    segs = build_blurpad_segments(_traj(kfs), clip_duration=6.0)
    assert [s.box.mode for s in segs] == [BLURPAD_MODE]


def test_blurpad_box_carries_full_source_frame():
    segs = build_blurpad_segments(_traj(_track(4), w=1920, h=1080), clip_duration=4.0)
    box = segs[0].box
    assert (box.x, box.y, box.w, box.h) == (0, 0, 1920, 1080)


def test_render_segment_span_property():
    segs = build_blurpad_segments(_traj(_track(4)), clip_duration=6.0)
    assert segs[0].span == 6.0
