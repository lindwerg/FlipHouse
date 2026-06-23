"""crop_geometry — crop window math, even-bound clamping, narrow-source fill, types.

The vertical reframe ALWAYS fills the frame with a 9:16 crop (founder mandate:
never blur-pad), so ``compute_crop_box`` ALWAYS returns a ``CROP_MODE`` box.
"""

import pytest

from fliphouse_worker.clipping.crop_geometry import (
    CROP_MODE,
    GENERAL_MARK,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    _even,
    clip_filename,
    compute_crop_box,
    round_duration,
)


def test_facebox_center_and_area():
    f = FaceBox(x=100.0, y=50.0, w=40.0, h=60.0, score=0.9)
    assert f.center_x == 120.0
    assert f.area == 2400.0


def test_even_rounds_down():
    assert _even(607) == 606
    assert _even(608) == 608


def test_compute_crop_box_centers_on_face():
    box = compute_crop_box(1920, 1080, center_x=960.0)
    assert box.mode == CROP_MODE
    assert box.h == 1080
    # full-height 9:16 column width = even(round(1080*1080/1920)) = even(round(607.5)) = 608
    assert box.w == 608
    # centered on 960 → x = even(clamp(960 - 304)) = even(656) = 656
    assert box.x == 656
    assert box.x + box.w <= 1920


def test_compute_crop_box_centers_when_no_face():
    box = compute_crop_box(1920, 1080, center_x=None)
    assert box.mode == CROP_MODE
    assert box.x == _even((1920 - box.w) // 2)


def test_compute_crop_box_fills_full_width_when_source_narrower_than_9_16():
    # A portrait/near-square source can't yield a 9:16 column wider than itself, so
    # the crop spans the full width and scales to FILL the frame — never blur-pad.
    box = compute_crop_box(400, 1080, center_x=200.0)
    assert box.mode == CROP_MODE
    assert (box.x, box.y, box.w, box.h) == (0, 0, 400, 1080)


def test_compute_crop_box_fills_full_width_for_vertical_source():
    # A genuinely vertical source: the 9:16 crop is the full width, centered.
    box = compute_crop_box(720, 1280, center_x=None)
    assert box.mode == CROP_MODE
    assert (box.x, box.w) == (0, 720)


def test_compute_crop_box_clamps_face_at_far_right_edge():
    box = compute_crop_box(1920, 1080, center_x=1900.0)
    assert box.x + box.w <= 1920
    assert box.x >= 0


def test_compute_crop_box_clamps_face_at_far_left_edge():
    box = compute_crop_box(1920, 1080, center_x=10.0)
    assert box.x == 0


def test_compute_crop_box_dims_are_even():
    box = compute_crop_box(1921, 1081, center_x=961.0)
    assert box.w % 2 == 0
    assert box.x % 2 == 0


def test_compute_crop_box_raises_on_nonpositive_dims():
    with pytest.raises(ValueError):
        compute_crop_box(0, 1080, center_x=None)
    with pytest.raises(ValueError):
        compute_crop_box(1920, 0, center_x=None)


def test_trajectory_dominant_center_is_median_of_tracks():
    traj = CropTrajectory(
        keyframes=(
            CropKeyframe(0.0, 100.0, TRACK_MARK),
            CropKeyframe(0.5, 200.0, TRACK_MARK),
            CropKeyframe(1.0, 300.0, TRACK_MARK),
            CropKeyframe(1.5, None, GENERAL_MARK),
        ),
        source_width=1920,
        source_height=1080,
    )
    assert traj.dominant_center() == 200.0
    assert traj.is_general() is False


def test_is_general_iff_no_track_center():
    traj = CropTrajectory(
        keyframes=(CropKeyframe(0.0, None, GENERAL_MARK),),
        source_width=1920,
        source_height=1080,
    )
    assert traj.dominant_center() is None
    assert traj.is_general() is True


def test_clip_filename_zero_padded():
    assert clip_filename(0) == "clip_00.mp4"
    assert clip_filename(12) == "clip_12.mp4"


def test_round_duration():
    assert round_duration(10.0, 55.5) == 45.5
    assert round_duration(0.0, 1.23456) == 1.235
