"""speaker_region — active-face heuristic, trajectory build via fakes, GPU-ASD lane, gate."""

import sys

from fliphouse_worker.clipping.crop_geometry import TRACK_MARK, FaceBox
from fliphouse_worker.clipping.speaker_region import (
    PHASE3_GPU_ASD,
    SWITCH_COOLDOWN_FRAMES,
    GpuAsdSpeakerRegionSelector,
    HeuristicSpeakerRegionSelector,
    MediapipeSpeakerRegionSelector,
    build_speaker_region_selector,
    select_active_face,
)


def _frontal_landmarks(center_x: float):
    """Camera-facing 5-landmark set centred on ``center_x`` (nose between spread eyes)."""
    return (
        (center_x - 30.0, 100.0),  # right eye
        (center_x + 30.0, 100.0),  # left eye
        (center_x, 130.0),  # nose (centred → frontal)
        (center_x - 20.0, 150.0),  # right mouth
        (center_x + 20.0, 150.0),  # left mouth
    )


def _profile_landmarks(center_x: float):
    """Turned-away 5-landmark set: nose shoved past the eyes (a profile/back-of-head)."""
    return (
        (center_x - 5.0, 100.0),  # right eye
        (center_x + 5.0, 100.0),  # left eye (collapsed onto the near one)
        (center_x + 40.0, 130.0),  # nose past both eyes → profile
        (center_x - 3.0, 150.0),
        (center_x + 3.0, 150.0),
    )


def _face(center_x: float, area_side: float) -> FaceBox:
    return FaceBox(x=center_x - area_side / 2, y=0.0, w=area_side, h=area_side, score=0.9)


def _frontal_face(center_x: float, area_side: float) -> FaceBox:
    return FaceBox(
        x=center_x - area_side / 2,
        y=0.0,
        w=area_side,
        h=area_side,
        score=0.9,
        landmarks=_frontal_landmarks(center_x),
    )


def _profile_face(center_x: float, area_side: float) -> FaceBox:
    return FaceBox(
        x=center_x - area_side / 2,
        y=0.0,
        w=area_side,
        h=area_side,
        score=0.9,
        landmarks=_profile_landmarks(center_x),
    )


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


def test_select_active_face_prefers_frontal_over_larger_profile():
    # Founder complaint 3: a SMALLER face facing the camera must win over a LARGER
    # head turned away (profile/back-of-head), instead of punching into the turned one.
    small_frontal = _frontal_face(300.0, 80.0)  # 6400 px²
    big_profile = _profile_face(900.0, 200.0)  # 40000 px², but turned away
    chosen, _ = select_active_face([small_frontal, big_profile], None, 0, 1000)
    assert chosen is small_frontal


def test_select_active_face_falls_back_to_largest_when_all_profiles():
    # Nobody faces the camera (only profiles): no frontal signal to act on, so the
    # legacy largest-face heuristic still applies (pool unchanged).
    small_profile = _profile_face(300.0, 80.0)
    big_profile = _profile_face(900.0, 200.0)
    chosen, _ = select_active_face([small_profile, big_profile], None, 0, 1000)
    assert chosen is big_profile


def test_select_active_face_frontal_pool_holds_during_cooldown():
    # During the anti-ping-pong cooldown the nearest FRONTAL face is held, never a
    # nearer turned/profile head.
    near_profile = _profile_face(480.0, 200.0)
    far_frontal = _frontal_face(900.0, 80.0)
    chosen, cooldown = select_active_face(
        [near_profile, far_frontal], prev_center_x=900.0, cooldown_left=3, src_w=1000
    )
    assert chosen is far_frontal  # frontal pool only → the profile is excluded
    assert cooldown == 2


def test_select_active_face_landmarkless_faces_use_legacy_largest():
    # MediaPipe boxes carry no landmarks (frontality None) → legacy largest-face pick.
    small, big = _face(100.0, 40.0), _face(800.0, 120.0)
    chosen, _ = select_active_face([small, big], None, 0, 1000)
    assert chosen is big


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


def test_mediapipe_selector_threads_active_face_box_to_keyframes():
    chosen = _face(500.0, 200.0)
    frames = ((chosen,),)  # single face → TRACK, so the active-face box survives
    sel = MediapipeSpeakerRegionSelector(
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1000, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    # The FULL bounding box of the active face survives, not just its center.
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[0].face == chosen


def _speaking_face(center_x: float, area_side: float, speaking: float) -> FaceBox:
    """A face with an ASD speaking score (no landmarks → frontality unknown)."""
    return FaceBox(
        x=center_x - area_side / 2,
        y=0.0,
        w=area_side,
        h=area_side,
        score=0.9,
        speaking=speaking,
    )


def test_phase3_flag_is_off():
    # Retired marker stays False (back-compat); the GPU-ASD lane is env-selected now.
    assert PHASE3_GPU_ASD is False


def test_select_active_face_follows_asd_speaker_over_larger_silent_head():
    # The profile/who-to-follow fix: a SMALLER talking face beats a LARGER silent one,
    # even though neither has frontality landmarks (the only-profiles case).
    small_talker = _speaking_face(300.0, 80.0, 0.95)
    big_silent = _speaking_face(900.0, 220.0, 0.02)
    chosen, _ = select_active_face([small_talker, big_silent], None, 0, 1000)
    assert chosen is small_talker


def test_select_active_face_asd_overrides_frontal_largest():
    # A turned-away SPEAKER beats a larger FRONTAL silent head: speech > frontality.
    turned_talker = _profile_face(300.0, 80.0)
    turned_talker = FaceBox(
        x=turned_talker.x,
        y=turned_talker.y,
        w=turned_talker.w,
        h=turned_talker.h,
        score=turned_talker.score,
        landmarks=turned_talker.landmarks,
        speaking=0.9,
    )
    frontal_silent = _frontal_face(900.0, 220.0)
    frontal_silent = FaceBox(
        x=frontal_silent.x,
        y=frontal_silent.y,
        w=frontal_silent.w,
        h=frontal_silent.h,
        score=frontal_silent.score,
        landmarks=frontal_silent.landmarks,
        speaking=0.05,
    )
    chosen, _ = select_active_face([turned_talker, frontal_silent], None, 0, 1000)
    assert chosen is turned_talker


def test_select_active_face_falls_back_to_frontal_when_nobody_speaks():
    # ASD signal present but EVERYONE sub-threshold → legacy frontal-largest applies.
    small_frontal = _frontal_face(300.0, 80.0)
    small_frontal = FaceBox(
        x=small_frontal.x,
        y=small_frontal.y,
        w=small_frontal.w,
        h=small_frontal.h,
        score=small_frontal.score,
        landmarks=small_frontal.landmarks,
        speaking=0.1,
    )
    big_profile = _profile_face(900.0, 220.0)
    big_profile = FaceBox(
        x=big_profile.x,
        y=big_profile.y,
        w=big_profile.w,
        h=big_profile.h,
        score=big_profile.score,
        landmarks=big_profile.landmarks,
        speaking=0.2,
    )
    chosen, _ = select_active_face([small_frontal, big_profile], None, 0, 1000)
    assert chosen is small_frontal  # frontal pool wins; no speaker resolved


def test_gpu_asd_selector_tracks_the_speaker_via_fake_transport():
    # End-to-end through the GPU-ASD selector with a FAKE transport (no network/GPU):
    # two turned heads, the SMALLER one talking → the trajectory tracks the talker.
    small_talker = _face(300.0, 80.0)
    big_silent = _face(900.0, 200.0)
    frames = ((small_talker, big_silent),)

    def fake_transport(src, start, end, sent_frames):
        # The selector hands the CPU-sampled frames; we score the smaller as speaking.
        assert sent_frames == frames
        return ((0.95, 0.01),)

    sel = GpuAsdSpeakerRegionSelector(
        asd_transport=fake_transport,
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1200, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.center_x is not None and kf.center_x < 500.0  # on the small talker, not big silent


def test_gpu_asd_selector_falls_back_on_transport_error():
    # A GPU/network fault must NEVER break the render: fall through to the CPU heuristic.
    frames = ((_face(500.0, 200.0),),)

    def boom(*a):
        raise RuntimeError("gpu down")

    sel = GpuAsdSpeakerRegionSelector(
        asd_transport=boom,
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1000, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    # The CPU fallback still produced a tracked trajectory off the same fake faces.
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.is_general() is False


def test_gpu_asd_selector_falls_back_on_shape_mismatch():
    # A malformed score grid (wrong frame/face count) is rejected → CPU fallback.
    frames = ((_face(500.0, 200.0),), (_face(520.0, 200.0),))
    sel = GpuAsdSpeakerRegionSelector(
        asd_transport=lambda *a: ((0.9,),),  # one row, but there are two frames
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1000, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    assert len(traj.keyframes) == 2  # fallback re-ran over both frames


def test_gpu_asd_selector_clamps_out_of_range_scores():
    # A noisy endpoint value outside [0,1] is clamped, not propagated — a >1 score
    # still reads as speaking; a negative one as silent.
    frames = ((_face(300.0, 80.0), _face(900.0, 200.0)),)
    sel = GpuAsdSpeakerRegionSelector(
        asd_transport=lambda *a: ((5.0, -2.0),),
        _sample_faces=lambda *a: frames,
        _probe_dims_fn=lambda s: (1200, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    assert traj.keyframes[0].center_x is not None
    assert traj.keyframes[0].center_x < 500.0  # tracked the clamped-to-speaking small face


def test_build_selector_returns_heuristic_when_disabled():
    sel = build_speaker_region_selector(env={})
    assert isinstance(sel, HeuristicSpeakerRegionSelector)


def test_build_selector_returns_gpu_asd_when_enabled():
    captured = {}

    def fake_factory(config):
        captured["endpoint"] = config.endpoint
        return lambda *a: ()

    sel = build_speaker_region_selector(
        env={
            "GPU_ASD_ENABLED": "true",
            "GPU_ASD_ENDPOINT": "https://asd.example",
            "GPU_ASD_SECRET": "shh",
        },
        _transport_factory=fake_factory,
    )
    assert isinstance(sel, GpuAsdSpeakerRegionSelector)
    assert captured["endpoint"] == "https://asd.example"


def test_build_selector_disabled_when_half_configured():
    # Flag on but no secret → fail closed to the CPU heuristic (never send unsigned).
    sel = build_speaker_region_selector(
        env={"GPU_ASD_ENABLED": "1", "GPU_ASD_ENDPOINT": "https://asd.example"}
    )
    assert isinstance(sel, HeuristicSpeakerRegionSelector)


def test_module_import_does_not_pull_mediapipe_or_cv2():
    # The heavy deps are lazy-imported only on the live render path.
    assert "mediapipe" not in sys.modules
    assert "cv2" not in sys.modules


def test_mediapipe_alias_points_at_the_heuristic_selector():
    # Back-compat: the historical name resolves to the YuNet→MediaPipe seam class.
    assert MediapipeSpeakerRegionSelector is HeuristicSpeakerRegionSelector


def test_selector_threads_yunet_landmarks_and_prefers_frontal_speaker():
    # End-to-end through the selector with FAKE YuNet output: a small frontal speaker
    # and a larger turned head co-present → the trajectory tracks the FRONTAL one.
    frontal = _frontal_face(300.0, 80.0)
    profile = _profile_face(900.0, 200.0)
    sel = HeuristicSpeakerRegionSelector(
        _sample_faces=lambda *a: ((frontal, profile),),
        _probe_dims_fn=lambda s: (1200, 1000),
    )
    traj = sel.select_speaker_region("src.mp4", 0.0, 1.0, [])
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    # Centre sits on the frontal speaker (≈300), not the larger turned head (≈900).
    assert kf.center_x is not None and kf.center_x < 500.0
