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
    # Avg face count > 1.2 → never wrong-crop a 2-shot; everything becomes GENERAL.
    samples = [RawSample(0.0, 400.0, 2), RawSample(0.5, 600.0, 2)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.is_general() is True
