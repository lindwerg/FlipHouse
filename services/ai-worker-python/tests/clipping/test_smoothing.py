"""build_trajectory — deadband hold, One-Euro pan, scene-cut snap, no-face/group GENERAL."""

from fliphouse_worker.clipping.crop_geometry import GENERAL_MARK, TRACK_MARK
from fliphouse_worker.clipping.smoothing import RawSample, build_trajectory


def test_deadband_holds_center_on_small_moves():
    samples = [RawSample(0.0, 520.0, 1), RawSample(0.5, 560.0, 1)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    # Both moves are within the 10% deadband (100 px) of the held center 500 → held.
    assert traj.keyframes[0].center_x == 500.0
    assert traj.keyframes[1].center_x == 500.0
    assert all(kf.mode == TRACK_MARK for kf in traj.keyframes)


def test_one_euro_pans_on_large_move():
    samples = [RawSample(0.0, 900.0, 1)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[0].center_x == 900.0  # first euro sample passes through


def test_scene_cut_snaps_held_center():
    samples = [RawSample(0.0, 520.0, 1), RawSample(0.5, 560.0, 1)]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1000, src_h=1000)
    # The cut at 0.5 resets the held center to the new sample, overriding the deadband.
    assert traj.keyframes[1].center_x == 560.0


def test_scene_cut_with_no_face_snaps_to_held():
    samples = [RawSample(0.0, 500.0, 1), RawSample(0.5, None, 0)]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1000, src_h=1000)
    # A cut on a faceless sample resets euro to the held center (no crash), marks GENERAL.
    assert traj.keyframes[1].mode == GENERAL_MARK


def test_marks_general_on_no_face():
    samples = [RawSample(0.0, None, 0), RawSample(0.5, None, 0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.is_general() is True
    assert all(kf.mode == GENERAL_MARK for kf in traj.keyframes)


def test_marks_general_on_group_shot():
    # Every sample is a 2-shot (face_count > 1) → never wrong-crop; all GENERAL.
    samples = [RawSample(0.0, 400.0, 2), RawSample(0.5, 600.0, 2)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.is_general() is True


def test_per_sample_general_only_marks_the_group_window():
    # The TRACK/GENERAL decision is PER SAMPLE: a single group-shot frame inside a
    # talking-head clip is GENERAL on its own, not a whole-clip force.
    samples = [
        RawSample(0.0, 500.0, 1),  # single face → TRACK
        RawSample(0.5, 500.0, 2),  # group shot → GENERAL (this sample only)
        RawSample(1.0, 500.0, 1),  # single face → TRACK
    ]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert [kf.mode for kf in traj.keyframes] == [TRACK_MARK, GENERAL_MARK, TRACK_MARK]
    assert traj.is_general() is False  # mixed clip still tracks the single-face windows


def test_track_center_preserved_across_a_faceless_gap():
    samples = [RawSample(0.0, 800.0, 1), RawSample(0.5, None, 0), RawSample(1.0, 800.0, 1)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    tracks = [kf.center_x for kf in traj.keyframes if kf.mode == TRACK_MARK]
    assert tracks == [800.0, 800.0]  # centre survives the GENERAL sample between


def test_face_near_frame_edge_marks_general():
    # A face within the 10% edge margin (leaving frame into b-roll) → show whole frame.
    samples = [RawSample(0.0, 50.0, 1)]  # centre at 5% of width
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK
