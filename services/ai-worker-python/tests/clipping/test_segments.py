"""segments — debounced mode FSM + run-length interval builder (dynamic reframe)."""

from fliphouse_worker.clipping.crop_geometry import (
    BLURPAD_MODE,
    CROP_MODE,
    GENERAL_MARK,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
)
from fliphouse_worker.clipping.segments import (
    RenderSegment,
    build_render_segments,
    resolve_mode_timeline,
)


def _kf(t: float, mode: str, cx: float | None = 960.0) -> CropKeyframe:
    return CropKeyframe(t, cx if mode == TRACK_MARK else None, mode)


def _track(n: int, *, cx: float = 960.0, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, TRACK_MARK, cx) for i in range(n)]


def _general(n: int, *, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, GENERAL_MARK) for i in range(n)]


def _traj(keyframes: list[CropKeyframe], *, w: int = 1920, h: int = 1080) -> CropTrajectory:
    return CropTrajectory(tuple(keyframes), w, h)


# ── resolve_mode_timeline ──────────────────────────────────────────────────


def test_timeline_empty_is_empty():
    assert resolve_mode_timeline(()) == ()


def test_timeline_seeds_crop_from_first_track_no_blurpad_intro():
    modes = resolve_mode_timeline(_track(3))
    assert modes == (CROP_MODE, CROP_MODE, CROP_MODE)  # no spurious blur-pad opening


def test_timeline_seeds_blurpad_from_first_general():
    modes = resolve_mode_timeline(_general(3))
    assert modes == (BLURPAD_MODE, BLURPAD_MODE, BLURPAD_MODE)


def test_timeline_single_general_below_n_drop_does_not_switch():
    # one dropped face inside a tracked run must NOT flip to blur-pad (n_drop=3)
    kfs = _track(3) + _general(1, start_idx=3) + _track(3, start_idx=4)
    assert set(resolve_mode_timeline(kfs)) == {CROP_MODE}


def test_timeline_switches_to_blurpad_after_n_drop():
    kfs = _track(2) + _general(3, start_idx=2)
    modes = resolve_mode_timeline(kfs)
    assert modes[-1] == BLURPAD_MODE  # 3 consecutive GENERAL crossed n_drop
    assert modes[2] == CROP_MODE and modes[3] == CROP_MODE  # still sticky for the first two


def test_timeline_returns_to_crop_after_n_acquire():
    kfs = _general(2) + _track(2, start_idx=2)
    modes = resolve_mode_timeline(kfs)
    assert modes[-1] == CROP_MODE  # 2 consecutive TRACK crossed n_acquire


# ── build_render_segments ──────────────────────────────────────────────────


def test_pure_track_is_one_crop_segment():
    segs = build_render_segments(_traj(_track(4, cx=960.0)), clip_duration=6.0)
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE
    assert (segs[0].start_s, segs[0].end_s) == (0.0, 6.0)


def test_pure_general_is_one_blurpad_segment():
    segs = build_render_segments(_traj(_general(4)), clip_duration=6.0)
    assert len(segs) == 1 and segs[0].box.mode == BLURPAD_MODE


def test_no_keyframes_yields_single_blurpad_failsafe():
    segs = build_render_segments(_traj([]), clip_duration=8.0)
    assert segs == (RenderSegment(0.0, 8.0, segs[0].box),)
    assert segs[0].box.mode == BLURPAD_MODE


def _three_segment_traj() -> CropTrajectory:
    return _traj(
        _track(6, cx=960.0)  # idx 0..5  → CROP
        + _general(3, start_idx=6)  # idx 6..8  → BLURPAD (after n_drop)
        + _track(3, cx=500.0, start_idx=9)  # idx 9..11 → CROP again
    )


def test_track_general_track_is_three_contiguous_segments():
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0)
    assert [s.box.mode for s in segs] == [CROP_MODE, BLURPAD_MODE, CROP_MODE]
    # contiguous, full coverage [0, clip_duration]
    assert segs[0].start_s == 0.0 and segs[-1].end_s == 6.0
    for a, b in zip(segs, segs[1:], strict=False):
        assert a.end_s == b.start_s


def test_crop_box_centre_is_run_median():
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0)
    # first CROP run centres all 960; last CROP run centres all 500 → distinct columns
    assert segs[0].box.x != segs[2].box.x


def test_scene_cut_in_transition_snaps_boundary_to_cut():
    # the CROP→BLURPAD transition window is [3.5, 4.0]; a cut at 3.8 inside it
    # snaps the boundary to the cut (mode flip lands on the visible cut).
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0, scene_cut_times=(3.8,))
    assert segs[0].end_s == 3.8


def test_micro_segment_is_merged_away():
    # with a large floor the 1.5s blur-pad run is merged into its neighbours → 1 CROP
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0, min_segment_s=3.0)
    assert len(segs) == 1 and segs[0].box.mode == CROP_MODE


def test_narrow_source_track_run_falls_back_to_blurpad_box():
    segs = build_render_segments(_traj(_track(4, cx=200.0), w=400, h=1080), clip_duration=4.0)
    assert len(segs) == 1 and segs[0].box.mode == BLURPAD_MODE  # too narrow for a 9:16 column


def test_lone_transient_face_in_broll_stays_one_blurpad():
    kfs = _general(3) + _track(1, cx=960.0, start_idx=3) + _general(3, start_idx=4)
    segs = build_render_segments(_traj(kfs), clip_duration=5.0)
    assert len(segs) == 1 and segs[0].box.mode == BLURPAD_MODE


def test_render_segment_span_property():
    segs = build_render_segments(_traj(_track(4)), clip_duration=6.0)
    assert segs[0].span == 6.0


def test_short_first_segment_merges_forward_and_coalesce_walks():
    # First run is a short blur-pad → merged into the next; the coalesce pass then
    # walks past the (differing) CROP/BLURPAD leading pair without collapsing it.
    kfs = _general(2) + _track(4, start_idx=2) + _general(4, start_idx=6)
    segs = build_render_segments(_traj(kfs), clip_duration=8.0, min_segment_s=2.0)
    assert [s.box.mode for s in segs] == [CROP_MODE, BLURPAD_MODE]
    assert segs[0].start_s == 0.0  # short opening blur-pad absorbed into the CROP run
