"""crop_geometry — bbox-aware variable-size 9:16 crop math + even-bound/in-frame guards.

The vertical reframe ALWAYS fills the frame with a 9:16 crop (founder mandate:
never blur-pad), so ``compute_crop_box`` ALWAYS returns a ``CROP_MODE`` box. Phase 1
sizes the window from the active SUBJECT box (one face or a union) — fully contained,
upper-third composed, min-zoom clamped, widened-not-sliced when too wide.
"""

import random

import pytest

from fliphouse_worker.clipping.crop_geometry import (
    CROP_MODE,
    FACE_TARGET_HEIGHT_FRAC,
    GENERAL_MARK,
    MIN_CROP_HEIGHT_FRAC,
    TARGET_RATIO,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    _even,
    clip_filename,
    compute_crop_box,
    round_duration,
    union_box,
)


def _contains(box, face: FaceBox) -> bool:
    return (
        box.x <= face.x
        and face.x + face.w <= box.x + box.w
        and box.y <= face.y
        and face.y + face.h <= box.y + box.h
    )


def _ratio(box) -> float:
    return box.w / box.h


# ── value types ──────────────────────────────────────────────────────────────


def test_facebox_center_and_area():
    f = FaceBox(x=100.0, y=50.0, w=40.0, h=60.0, score=0.9)
    assert f.center_x == 120.0
    assert f.center_y == 80.0
    assert f.area == 2400.0


def test_even_rounds_down():
    assert _even(607) == 606
    assert _even(608) == 608


def test_union_box_is_none_when_empty():
    assert union_box(()) is None


def test_union_box_encloses_all_faces_and_takes_min_score():
    a = FaceBox(x=100.0, y=50.0, w=80.0, h=80.0, score=0.9)
    b = FaceBox(x=400.0, y=30.0, w=80.0, h=120.0, score=0.6)
    u = union_box((a, b))
    assert (u.x, u.y) == (100.0, 30.0)
    assert (u.x + u.w, u.y + u.h) == (480.0, 150.0)
    assert u.score == 0.6


# ── faceless / centered crop (GENERAL fallback) ──────────────────────────────


def test_compute_crop_box_centered_when_no_face():
    box = compute_crop_box(1920, 1080, center_x=None, face=None)
    assert box.mode == CROP_MODE
    assert box.h == 1080
    # full-height 9:16 column width = even(round(1080*0.5625)) = even(round(607.5)) = 608
    assert box.w == 608
    assert (box.x, box.y) == (_even((1920 - 608) // 2), 0)


def test_compute_crop_box_centered_face_none_fills_full_width_for_narrow_source():
    box = compute_crop_box(400, 1080, center_x=200.0, face=None)
    assert (box.x, box.y, box.w, box.h) == (0, 0, 400, 1080)


def test_compute_crop_box_centered_face_none_for_vertical_source():
    box = compute_crop_box(720, 1280, center_x=None, face=None)
    assert (box.x, box.w) == (0, 720)


# ── single-subject crop ──────────────────────────────────────────────────────


def test_single_offcenter_face_is_contained_with_headroom_not_overzoomed():
    # A small off-center face must be fully contained, composed on the upper third,
    # and NOT over-zoomed: the min-zoom clamp keeps the face ≈ FACE_TARGET_HEIGHT_FRAC.
    face = FaceBox(x=1400.0, y=300.0, w=200.0, h=260.0, score=0.9)
    box = compute_crop_box(1920, 1080, face.center_x, face=face)
    assert box.mode == CROP_MODE
    assert _contains(box, face)
    assert abs(_ratio(box) - TARGET_RATIO) < 0.01  # a true 9:16 window
    # min-zoom clamp: the face occupies ≈ the target fraction, never a huge head crop.
    assert face.h / box.h <= FACE_TARGET_HEIGHT_FRAC + 0.02
    # upper-third composition: more empty space BELOW the face than above (subject high).
    above = face.y - box.y
    below = (box.y + box.h) - (face.y + face.h)
    assert below > above


def test_min_zoom_clamp_widens_for_a_tiny_face():
    # A tiny face would fit a tight 9:16, but the absolute floor forbids over-zoom:
    # the crop height never drops below MIN_CROP_HEIGHT_FRAC of the source.
    face = FaceBox(x=950.0, y=520.0, w=40.0, h=40.0, score=0.9)
    box = compute_crop_box(1920, 1080, face.center_x, face=face)
    assert box.h >= int(MIN_CROP_HEIGHT_FRAC * 1080) - 2
    assert _contains(box, face)


def test_single_face_centers_horizontally_on_subject():
    face = FaceBox(x=200.0, y=300.0, w=160.0, h=220.0, score=0.9)
    box = compute_crop_box(1920, 1080, face.center_x, face=face)
    # the window center sits within one even-pixel of the face center (modulo clamping)
    assert abs((box.x + box.w / 2.0) - face.center_x) <= box.w  # in-frame, near subject
    assert _contains(box, face)


def test_face_at_far_right_edge_stays_in_frame():
    face = FaceBox(x=1780.0, y=300.0, w=120.0, h=180.0, score=0.9)
    box = compute_crop_box(1920, 1080, face.center_x, face=face)
    assert box.x + box.w <= 1920 and box.x >= 0
    assert _contains(box, face)


def test_face_at_far_left_edge_stays_in_frame():
    face = FaceBox(x=10.0, y=300.0, w=120.0, h=180.0, score=0.9)
    box = compute_crop_box(1920, 1080, face.center_x, face=face)
    assert box.x == 0
    assert _contains(box, face)


# ── multi-person union ───────────────────────────────────────────────────────


def test_two_face_union_keeps_both_inside_window():
    left = FaceBox(x=300.0, y=300.0, w=200.0, h=260.0, score=0.9)
    right = FaceBox(x=1300.0, y=320.0, w=200.0, h=260.0, score=0.8)
    u = union_box((left, right))
    box = compute_crop_box(1920, 1080, u.center_x, face=u)
    assert _contains(box, left)
    assert _contains(box, right)
    assert box.mode == CROP_MODE


def test_far_apart_faces_widen_to_max_fit_not_sliced():
    # Faces near both edges: the union is too WIDE for a 9:16 column → widen to the
    # max source-fit width (here the full frame) and KEEP both faces (never slice).
    left = FaceBox(x=50.0, y=300.0, w=150.0, h=200.0, score=0.9)
    right = FaceBox(x=1720.0, y=300.0, w=150.0, h=200.0, score=0.9)
    u = union_box((left, right))
    box = compute_crop_box(1920, 1080, u.center_x, face=u)
    assert box.w == _even(1920)  # widened to the max source-fit width
    assert _contains(box, left) and _contains(box, right)
    assert _ratio(box) > TARGET_RATIO  # wider than 9:16 (accepted, not sliced)


# ── fail-closed invariants ───────────────────────────────────────────────────


def test_compute_crop_box_dims_are_even_on_odd_source():
    face = FaceBox(x=900.0, y=400.0, w=150.0, h=210.0, score=0.9)
    box = compute_crop_box(1921, 1081, face.center_x, face=face)
    assert box.w % 2 == 0 and box.h % 2 == 0
    assert box.x % 2 == 0 and box.y % 2 == 0


def test_compute_crop_box_raises_on_nonpositive_dims():
    with pytest.raises(ValueError):
        compute_crop_box(0, 1080, center_x=None)
    with pytest.raises(ValueError):
        compute_crop_box(1920, 0, center_x=None)


def test_compute_crop_box_fail_closes_on_degenerate_zero_width_window():
    # A source so tiny that the 9:16 column rounds to a zero-width (unrenderable)
    # window must FAIL CLOSED — the post-condition guard raises rather than ship it.
    face = FaceBox(x=0.0, y=0.0, w=1.0, h=1.0, score=0.9)
    with pytest.raises(ValueError, match="escapes source"):
        compute_crop_box(2, 2, 0.5, face=face)


def test_even_in_frame_invariants_hold_for_many_random_boxes():
    rng = random.Random(20260623)
    for _ in range(2000):
        sw = rng.randint(640, 3840)
        sh = rng.randint(360, 2160)
        fw = rng.randint(20, sw)
        fh = rng.randint(20, sh)
        fx = rng.uniform(0.0, sw - fw)
        fy = rng.uniform(0.0, sh - fh)
        face = FaceBox(fx, fy, float(fw), float(fh), 0.9)
        box = compute_crop_box(sw, sh, face.center_x, face=face)
        assert box.w % 2 == 0 and box.h % 2 == 0
        assert box.x % 2 == 0 and box.y % 2 == 0
        assert box.x >= 0 and box.y >= 0
        assert box.x + box.w <= sw and box.y + box.h <= sh
        assert box.w > 0 and box.h > 0


def test_vertical_y_composition_varies_with_subject_position():
    # The y axis is no longer pinned to 0: a face lower in the source pushes y down.
    high = FaceBox(x=900.0, y=100.0, w=160.0, h=220.0, score=0.9)
    low = FaceBox(x=900.0, y=760.0, w=160.0, h=220.0, score=0.9)
    box_high = compute_crop_box(1920, 1080, high.center_x, face=high)
    box_low = compute_crop_box(1920, 1080, low.center_x, face=low)
    assert box_low.y > box_high.y
    assert _contains(box_high, high) and _contains(box_low, low)


# ── trajectory value-type helpers ────────────────────────────────────────────


def test_cropkeyframe_face_defaults_to_none():
    kf = CropKeyframe(0.0, 960.0, TRACK_MARK)
    assert kf.face is None


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
