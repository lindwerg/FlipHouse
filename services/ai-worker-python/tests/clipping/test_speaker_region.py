"""speaker_region — active-face heuristic, trajectory build via fakes, GPU stub, flag-gate."""

import sys

import pytest

from fliphouse_worker.clipping.crop_geometry import TRACK_MARK, FaceBox
from fliphouse_worker.clipping.speaker_region import (
    PHASE3_GPU_ASD,
    SWITCH_COOLDOWN_FRAMES,
    GpuAsdSpeakerRegionSelector,
    MediapipeSpeakerRegionSelector,
    select_active_face,
)


def _face(center_x: float, area_side: float) -> FaceBox:
    return FaceBox(x=center_x - area_side / 2, y=0.0, w=area_side, h=area_side, score=0.9)


def test_select_active_face_none_when_no_faces_and_decays_cooldown():
    assert select_active_face([], None, 0, 1000) == (None, 0)
    assert select_active_face([], 500.0, 3, 1000) == (None, 2)


def test_select_active_face_picks_largest_when_no_prev():
    small, big = _face(100.0, 40.0), _face(800.0, 120.0)
    chosen, cooldown = select_active_face([small, big], None, 0, 1000)
    assert chosen is big
    assert cooldown == SWITCH_COOLDOWN_FRAMES  # a switch (no prev) arms the cooldown


def test_select_active_face_stickiness_keeps_smaller_nearby_face():
    near_small = _face(500.0, 60.0)  # 3600 px² near prev → ×3 bonus = 10800
    far_big = _face(900.0, 90.0)  # 8100 px², but far → no bonus; loses to the boosted near face
    chosen, cooldown = select_active_face(
        [near_small, far_big], prev_center_x=500.0, cooldown_left=0, src_w=1000
    )
    assert chosen is near_small
    assert cooldown == 0  # no switch (stuck to the near face) → cooldown decays toward 0


def test_select_active_face_holds_nearest_during_cooldown():
    a, b = _face(480.0, 40.0), _face(900.0, 200.0)
    chosen, cooldown = select_active_face([a, b], prev_center_x=500.0, cooldown_left=3, src_w=1000)
    assert chosen is a  # nearest to prev, NOT largest — anti ping-pong
    assert cooldown == 2


def test_select_active_face_switches_to_far_larger_face():
    far_big = _face(900.0, 200.0)
    chosen, cooldown = select_active_face(
        [far_big], prev_center_x=100.0, cooldown_left=0, src_w=1000
    )
    assert chosen is far_big
    assert cooldown == SWITCH_COOLDOWN_FRAMES


def test_mediapipe_selector_builds_trajectory_from_fakes():
    frames = ((_face(500.0, 200.0),), (_face(520.0, 200.0),))
    sel = MediapipeSpeakerRegionSelector(
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1000, 1000),
        sample_fps=2.0,
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    assert traj.source_width == 1000
    assert len(traj.keyframes) == 2
    assert all(kf.mode == TRACK_MARK for kf in traj.keyframes)
    assert traj.is_general() is False


def test_mediapipe_selector_uses_only_injected_seams():
    calls = {"sample": 0, "probe": 0}

    def sample(*a):
        calls["sample"] += 1
        return ((_face(500.0, 200.0),),)

    def probe(s):
        calls["probe"] += 1
        return (1000, 1000)

    sel = MediapipeSpeakerRegionSelector(_sample_faces=sample, _probe_dims_fn=probe)
    sel.select_speaker_region("src.mp4", 10.0, 20.0, [5.0, 15.0, 95.0])
    # No per-clip scene-cut rescan: exactly one sample + one probe call, no ffmpeg.
    assert calls == {"sample": 1, "probe": 1}


def test_mediapipe_selector_handles_faceless_frames():
    sel = MediapipeSpeakerRegionSelector(
        _sample_faces=lambda *a: ((), ()),
        _probe_dims_fn=lambda s: (1000, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    assert traj.is_general() is True


def test_gpu_asd_stub_raises():
    with pytest.raises(NotImplementedError, match="PHASE3"):
        GpuAsdSpeakerRegionSelector().select_speaker_region("src.mp4", 0.0, 1.0, [])


def test_phase3_flag_is_off():
    assert PHASE3_GPU_ASD is False


def test_module_import_does_not_pull_mediapipe_or_cv2():
    # The heavy deps are lazy-imported only on the live render path.
    assert "mediapipe" not in sys.modules
    assert "cv2" not in sys.modules
