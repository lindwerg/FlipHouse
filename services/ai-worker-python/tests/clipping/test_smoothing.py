"""build_trajectory — deadband/One-Euro center, asymmetric zoom, scene-cut reset,
co-present union subject, faceless/edge/crowd GENERAL."""

from fliphouse_worker.clipping.crop_geometry import GENERAL_MARK, TRACK_MARK, FaceBox
from fliphouse_worker.clipping.smoothing import (
    ZOOM_IN_EASE,
    ZOOM_OUT_EASE,
    RawSample,
    _ease_zoom,
    _scaled_box,
    build_trajectory,
)


def _face(center_x: float, side: float = 100.0) -> FaceBox:
    return FaceBox(x=center_x - side / 2.0, y=400.0, w=side, h=side, score=0.9)


def _single(t: float, center_x: float, side: float = 100.0) -> RawSample:
    f = _face(center_x, side)
    return RawSample(t, center_x, 1, face=f, faces=(f,))


def test_deadband_holds_center_on_small_moves():
    samples = [_single(0.0, 520.0), _single(0.5, 560.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    # Both moves are within the 10% deadband (100 px) of the held center 500 → held.
    assert traj.keyframes[0].center_x == 500.0
    assert traj.keyframes[1].center_x == 500.0
    assert all(kf.mode == TRACK_MARK for kf in traj.keyframes)


def test_one_euro_pans_on_large_move():
    samples = [_single(0.0, 900.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[0].center_x == 900.0  # first euro sample passes through


def test_scene_cut_snaps_held_center():
    samples = [_single(0.0, 520.0), _single(0.5, 560.0)]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1000, src_h=1000)
    # The cut at 0.5 resets the held center to the new sample, overriding the deadband.
    assert traj.keyframes[1].center_x == 560.0


def test_scene_cut_with_no_face_snaps_to_held():
    samples = [_single(0.0, 500.0), RawSample(0.5, None, 0)]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1000, src_h=1000)
    # A cut on a faceless sample resets euro to the held center (no crash), marks GENERAL.
    assert traj.keyframes[1].mode == GENERAL_MARK


def test_marks_general_on_no_face():
    samples = [RawSample(0.0, None, 0), RawSample(0.5, None, 0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.is_general() is True
    assert all(kf.mode == GENERAL_MARK for kf in traj.keyframes)


def test_two_co_present_faces_track_their_union_not_general():
    # The multi-person fix: 2 co-present faces are TRACK on their UNION (everyone kept),
    # NOT GENERAL/center on the empty gap between heads.
    # Close-enough heads (their union fits one undistorted 9:16 crop) → union TRACK.
    left, right = _face(400.0), _face(600.0)
    samples = [RawSample(0.0, 400.0, 2, face=left, faces=(left, right))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.center_x == 500.0  # union center, between the two heads
    assert kf.face is not None and kf.face.center_x == 500.0


def test_three_co_present_faces_still_union_track():
    a, b, c = _face(400.0), _face(500.0), _face(600.0)
    samples = [RawSample(0.0, 400.0, 3, face=a, faces=(a, b, c))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[0].center_x == 500.0  # centered across all three


def test_moderately_spread_faces_keep_both_in_widest_crop_not_dominant():
    # Heads too spread for the TIGHT padded union, but both still inside the WIDEST
    # source-fit 9:16 window → keep EVERYONE (union), framed wider, NOT a punch-in
    # onto one head. (Widest 9:16 in 1920x1080 = 607.5; raw union 560 <= 607.5.)
    left = FaceBox(x=720.0, y=380.0, w=150.0, h=210.0, score=0.9)
    right = FaceBox(x=1130.0, y=380.0, w=150.0, h=210.0, score=0.8)
    samples = [RawSample(0.0, 795.0, 2, face=left, faces=(left, right))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.face.center_x == 1000.0  # union center, both kept


def test_far_apart_co_present_follows_dominant_face_not_union():
    # Heads SO far apart that even the WIDEST 9:16 cannot hold both: keeping both would
    # stretch or show the empty gap, so the subject is the DOMINANT (larger) face.
    small = FaceBox(x=80.0, y=400.0, w=90.0, h=90.0, score=0.9)
    big = FaceBox(x=820.0, y=400.0, w=160.0, h=160.0, score=0.9)
    samples = [RawSample(0.0, 125.0, 2, face=small, faces=(small, big))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.face.center_x == big.center_x  # the larger head


def test_co_present_count_without_faces_degrades_to_general():
    # Defensive: face_count says 2 but no boxes present → GENERAL, never crash.
    samples = [RawSample(0.0, 500.0, 2, face=None, faces=())]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK


def test_true_crowd_above_co_present_max_is_general():
    faces = tuple(_face(100.0 + 150.0 * i) for i in range(4))  # 4 faces > CO_PRESENT_MAX
    samples = [RawSample(0.0, 100.0, 4, face=faces[0], faces=faces)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK


def test_per_sample_general_only_marks_the_crowd_window():
    # PER SAMPLE: a lone crowd frame inside a talking-head clip is GENERAL on its own.
    crowd = tuple(_face(100.0 + 150.0 * i) for i in range(4))
    samples = [
        _single(0.0, 500.0),  # single face → TRACK
        RawSample(0.5, 100.0, 4, face=crowd[0], faces=crowd),  # crowd → GENERAL
        _single(1.0, 500.0),  # single face → TRACK
    ]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert [kf.mode for kf in traj.keyframes] == [TRACK_MARK, GENERAL_MARK, TRACK_MARK]
    assert traj.is_general() is False


def test_track_center_preserved_across_a_faceless_gap():
    samples = [_single(0.0, 800.0), RawSample(0.5, None, 0), _single(1.0, 800.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    tracks = [kf.center_x for kf in traj.keyframes if kf.mode == TRACK_MARK]
    assert tracks == [800.0, 800.0]  # centre survives the GENERAL sample between


def test_face_near_frame_edge_marks_general():
    # A single face within the 10% edge margin (leaving frame into b-roll) → whole frame.
    samples = [_single(0.0, 50.0)]  # centre at 5% of width
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK


def test_track_keyframe_carries_scaled_subject_box():
    samples = [_single(0.0, 500.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == TRACK_MARK
    # First (post-reset) zoom sample passes the height through unchanged.
    assert traj.keyframes[0].face is not None
    assert traj.keyframes[0].face.h == 100.0
    assert traj.keyframes[0].face.center_x == 500.0


def test_general_keyframe_drops_the_face_box():
    samples = [RawSample(0.0, None, 0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK
    assert traj.keyframes[0].face is None


def test_rawsample_face_and_faces_default_empty():
    s = RawSample(0.0, 500.0, 1)
    assert s.face is None
    assert s.faces == ()


# ── asymmetric zoom easing ───────────────────────────────────────────────────


def test_ease_zoom_first_sample_passes_through():
    assert _ease_zoom(None, 300.0) == 300.0


def test_ease_zoom_out_is_fast():
    # Growing the window (subject got bigger) uses the FAST factor.
    assert _ease_zoom(100.0, 200.0) == 100.0 + ZOOM_OUT_EASE * 100.0


def test_ease_zoom_in_is_slow():
    # Shrinking the window (subject got smaller) uses the SLOW factor.
    assert _ease_zoom(200.0, 100.0) == 200.0 + ZOOM_IN_EASE * -100.0


def test_zoom_out_eases_faster_than_zoom_in_over_a_clip():
    big, small = _face(500.0, 200.0), _face(500.0, 100.0)
    grow = [RawSample(0.0, 500.0, 1, face=small, faces=(small,))]
    grow += [RawSample(0.5, 500.0, 1, face=big, faces=(big,))]
    traj_grow = build_trajectory(grow, scene_cut_times=[], src_w=2000, src_h=2000)
    # second sample: zoom-OUT toward 200 from 100 → fast ease closes most of the gap
    assert traj_grow.keyframes[1].face.h == 100.0 + ZOOM_OUT_EASE * 100.0


def test_scene_cut_hard_resets_zoom_axis():
    small, big = _face(500.0, 100.0), _face(500.0, 200.0)
    samples = [
        RawSample(0.0, 500.0, 1, face=small, faces=(small,)),
        RawSample(0.5, 500.0, 1, face=big, faces=(big,)),  # cut here → zoom passes through
    ]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=2000, src_h=2000)
    assert traj.keyframes[1].face.h == 200.0  # reset → no easing across the cut


def test_scaled_box_zero_height_returns_unchanged():
    degenerate = FaceBox(x=0.0, y=0.0, w=10.0, h=0.0, score=0.5)
    assert _scaled_box(degenerate, 50.0) is degenerate
