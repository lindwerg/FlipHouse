"""segments — debounced mode FSM + run-length interval builder (dynamic reframe).

Founder mandate: the vertical reframe ALWAYS fills the frame with a 9:16 crop —
TRACK runs crop the speaker column, GENERAL runs crop the CENTER column. NO segment
ever blur-pads, so every emitted box is ``CROP_MODE``.
"""

from fliphouse_worker.clipping.crop_geometry import (
    BLURPAD_MODE,
    CONTAIN_LAYOUT,
    CROP_MODE,
    GENERAL_MARK,
    SINGLE_LAYOUT,
    STACK_LAYOUT,
    TRACK_MARK,
    CropKeyframe,
    CropTrajectory,
    FaceBox,
    compute_contain_box,
    compute_crop_box,
)
from fliphouse_worker.clipping.segments import (
    RenderSegment,
    _run_face,
    _stack_panels_for_run,
    build_render_segments,
    resolve_mode_timeline,
)


def _face(center_x: float) -> FaceBox:
    return FaceBox(x=center_x - 50.0, y=0.0, w=100.0, h=100.0, score=0.9)


def _frontal_face(cx: float, side: float = 150.0) -> FaceBox:
    return FaceBox(
        x=cx - side / 2.0,
        y=400.0,
        w=side,
        h=side,
        score=0.9,
        landmarks=(
            (cx - 30.0, 400.0),
            (cx + 30.0, 400.0),
            (cx, 430.0),
            (cx - 20.0, 450.0),
            (cx + 20.0, 450.0),
        ),
    )


def _stack_kf(t: float, panels: tuple[FaceBox, ...], cx: float = 960.0) -> CropKeyframe:
    union = FaceBox(x=0.0, y=400.0, w=1920.0, h=150.0, score=0.9)
    return CropKeyframe(t, cx, TRACK_MARK, face=union, panels=panels)


def _kf(t: float, mode: str, cx: float | None = 960.0) -> CropKeyframe:
    return CropKeyframe(t, cx if mode == TRACK_MARK else None, mode)


def _track(n: int, *, cx: float = 960.0, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, TRACK_MARK, cx) for i in range(n)]


def _general(n: int, *, start_idx: int = 0) -> list[CropKeyframe]:
    return [_kf((start_idx + i) * 0.5, GENERAL_MARK) for i in range(n)]


def _traj(keyframes: list[CropKeyframe], *, w: int = 1920, h: int = 1080) -> CropTrajectory:
    return CropTrajectory(tuple(keyframes), w, h)


def _three_segment_traj() -> CropTrajectory:
    return _traj(
        _track(6, cx=960.0)  # idx 0..5  → TRACK crop
        + _general(3, start_idx=6)  # idx 6..8  → GENERAL center crop (after n_drop)
        + _track(3, cx=500.0, start_idx=9)  # idx 9..11 → TRACK crop again
    )


# ── resolve_mode_timeline ──────────────────────────────────────────────────


def test_timeline_empty_is_empty():
    assert resolve_mode_timeline(()) == ()


def test_timeline_seeds_crop_from_first_track_no_general_intro():
    modes = resolve_mode_timeline(_track(3))
    assert modes == (CROP_MODE, CROP_MODE, CROP_MODE)  # no spurious center-crop opening


def test_timeline_seeds_general_from_first_general():
    modes = resolve_mode_timeline(_general(3))
    assert modes == (BLURPAD_MODE, BLURPAD_MODE, BLURPAD_MODE)


def test_timeline_single_general_below_n_drop_does_not_switch():
    # one dropped face inside a tracked run must NOT flip to GENERAL (n_drop=3)
    kfs = _track(3) + _general(1, start_idx=3) + _track(3, start_idx=4)
    assert set(resolve_mode_timeline(kfs)) == {CROP_MODE}


def test_timeline_switches_to_general_after_n_drop():
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


def test_pure_track_keeps_speaker_crop_not_contain():
    # The talking-head path is UNCHANGED: a TRACK run is a SINGLE speaker crop column,
    # never the b-roll full-frame CONTAIN. (Guards the founder invariant on reframe.)
    segs = build_render_segments(_traj(_track(4, cx=960.0)), clip_duration=6.0)
    assert segs[0].box.layout == SINGLE_LAYOUT
    assert segs[0].box.layout != CONTAIN_LAYOUT
    # a 9:16 speaker column of a 1920x1080 source — not the whole 1920-wide frame
    assert segs[0].box.w == 608


def test_pure_general_is_one_full_frame_contain_segment():
    # No speaker → b-roll CONTAIN: the WHOLE source frame stays in (founder: "чтобы
    # всё входило"), filled with a blurred margin — CROP_MODE, never blur-pad.
    segs = build_render_segments(_traj(_general(4)), clip_duration=6.0)
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE
    assert segs[0].box.layout == CONTAIN_LAYOUT
    expected = compute_contain_box(1920, 1080)
    assert (segs[0].box.x, segs[0].box.y, segs[0].box.w, segs[0].box.h) == (
        expected.x,
        expected.y,
        expected.w,
        expected.h,
    )


def test_no_keyframes_yields_single_center_crop_failsafe():
    segs = build_render_segments(_traj([]), clip_duration=8.0)
    assert segs == (RenderSegment(0.0, 8.0, segs[0].box),)
    assert segs[0].box.mode == CROP_MODE  # centered fill-crop, not blur-pad


def test_no_live_segment_is_ever_blurpad():
    # Guard: NO live path may emit a blur-pad/BLURPAD segment box.
    trajs = (_traj(_track(4)), _traj(_general(4)), _traj([]), _three_segment_traj())
    for traj in trajs:
        segs = build_render_segments(traj, clip_duration=6.0)
        assert all(s.box.mode == CROP_MODE for s in segs)


def test_track_general_track_is_three_contiguous_segments():
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0)
    assert [s.box.mode for s in segs] == [CROP_MODE, CROP_MODE, CROP_MODE]  # all fill-crops
    # contiguous, full coverage [0, clip_duration]
    assert segs[0].start_s == 0.0 and segs[-1].end_s == 6.0
    for a, b in zip(segs, segs[1:], strict=False):
        assert a.end_s == b.start_s


def test_track_general_track_columns_track_their_centers():
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0)
    centered = compute_crop_box(1920, 1080, center_x=None).x
    assert segs[0].box.x == centered  # speaker centered on 960 ≈ frame center
    # GENERAL/b-roll run → full-frame CONTAIN (whole frame in), not a center column.
    assert segs[1].box.layout == CONTAIN_LAYOUT
    assert (segs[1].box.x, segs[1].box.w) == (0, 1920)
    assert segs[2].box.layout == SINGLE_LAYOUT
    assert segs[2].box.x != centered  # speaker@500 shifts the crop column left


def test_scene_cut_in_transition_snaps_boundary_to_cut():
    # the TRACK→GENERAL transition window is [3.5, 4.0]; a cut at 3.8 inside it
    # snaps the boundary to the cut (mode flip lands on the visible cut).
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0, scene_cut_times=(3.8,))
    assert segs[0].end_s == 3.8


def test_micro_segment_is_merged_away():
    # with a large floor the 1.5s GENERAL run is merged into its neighbours → 1 segment
    segs = build_render_segments(_three_segment_traj(), clip_duration=6.0, min_segment_s=3.0)
    assert len(segs) == 1 and segs[0].box.mode == CROP_MODE


def test_narrow_source_general_run_is_full_frame_contain():
    # A b-roll GENERAL run CONTAINs the WHOLE frame regardless of source shape — the
    # box is the full (even-clamped) source frame, never a cropped column.
    segs = build_render_segments(_traj(_general(4), w=400, h=1080), clip_duration=4.0)
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE
    assert segs[0].box.layout == CONTAIN_LAYOUT
    assert (segs[0].box.x, segs[0].box.y, segs[0].box.w, segs[0].box.h) == (0, 0, 400, 1080)


def test_narrow_source_track_run_still_fills_with_crop():
    segs = build_render_segments(_traj(_track(4, cx=200.0), w=400, h=1080), clip_duration=4.0)
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE
    assert (segs[0].box.x, segs[0].box.w) == (0, 398)  # too narrow for a column → full width


def test_lone_transient_face_in_broll_stays_one_contain_segment():
    kfs = _general(3) + _track(1, cx=960.0, start_idx=3) + _general(3, start_idx=4)
    segs = build_render_segments(_traj(kfs), clip_duration=5.0)
    # the lone transient face never flips the steady b-roll run → one full-frame CONTAIN
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE and segs[0].box.layout == CONTAIN_LAYOUT


def test_render_segment_span_property():
    segs = build_render_segments(_traj(_track(4)), clip_duration=6.0)
    assert segs[0].span == 6.0


def test_short_first_segment_merges_forward_and_coalesce_walks():
    # First run is a short GENERAL → merged into the next; the coalesce pass then
    # walks past the (differing) TRACK/GENERAL leading pair without collapsing it.
    kfs = _general(2) + _track(4, start_idx=2) + _general(4, start_idx=6)
    segs = build_render_segments(_traj(kfs), clip_duration=8.0, min_segment_s=2.0)
    # both runs are fill-crops on different centers (speaker column vs center column)
    assert [s.box.mode for s in segs] == [CROP_MODE, CROP_MODE]
    assert segs[0].start_s == 0.0  # short opening GENERAL absorbed into the TRACK run


# ── _run_face — active-face box surfaced at the crop call site (Phase 0) ──────


def test_run_face_none_when_no_faces():
    assert _run_face([960.0], []) is None


def test_run_face_falls_back_to_first_when_no_centers():
    faces = [_face(400.0), _face(800.0)]
    assert _run_face([], faces) is faces[0]


def test_run_face_picks_face_nearest_run_median_center():
    faces = [_face(400.0), _face(950.0), _face(1500.0)]
    # median of the run's tracked centers is 960 → nearest face is the 950 box.
    assert _run_face([900.0, 960.0, 1020.0], faces) is faces[1]


def test_face_bbox_sizes_the_crop_window():
    # The active-subject box now SIZES the 9:16 window (variable height, upper-third),
    # so a TRACK run carrying a face yields a tighter window than a faceless full-height
    # center crop — and the face is fully contained.
    face = _face(960.0)  # 100x100 box centered at 960
    kfs = [CropKeyframe(i * 0.5, 960.0, TRACK_MARK, face=face) for i in range(4)]
    segs = build_render_segments(_traj(kfs), clip_duration=6.0)
    box = segs[0].box
    assert box.mode == CROP_MODE
    assert box.h < 1080  # sized down from the full-height center crop (no over-zoom-out)
    assert box.x <= face.x and face.x + face.w <= box.x + box.w  # face contained


# ── split-screen STACK runs ──────────────────────────────────────────────────


def _far_pair() -> tuple[FaceBox, FaceBox]:
    return _frontal_face(200.0), _frontal_face(1700.0)


def test_stack_run_yields_a_stack_box_with_two_panels():
    # A TRACK run whose keyframes all carry panels → ONE split-screen STACK segment.
    panels = _far_pair()
    kfs = [_stack_kf(i * 0.5, panels) for i in range(4)]
    segs = build_render_segments(_traj(kfs), clip_duration=6.0)
    assert len(segs) == 1
    box = segs[0].box
    assert box.mode == CROP_MODE and box.layout == STACK_LAYOUT
    assert len(box.panels) == 2


def test_stack_panels_for_run_majority_gate():
    panels = _far_pair()
    # 2 of 4 TRACK samples split → exactly the 0.5 fraction → STACK (>= boundary).
    assert _stack_panels_for_run([panels, panels], n_track=4) == panels
    # 1 of 4 split → below the majority → keep one window.
    assert _stack_panels_for_run([panels], n_track=4) == ()
    # no split frames at all → keep one window.
    assert _stack_panels_for_run([], n_track=4) == ()


def test_transient_single_split_frame_does_not_flip_a_single_window_run():
    # A run that is mostly single-window with ONE stray split frame stays SINGLE.
    face = _face(960.0)
    kfs = [CropKeyframe(i * 0.5, 960.0, TRACK_MARK, face=face) for i in range(4)]
    kfs[1] = _stack_kf(0.5, _far_pair())  # one transient split among four
    segs = build_render_segments(_traj(kfs), clip_duration=6.0)
    assert segs[0].box.layout == SINGLE_LAYOUT


def test_stack_run_panels_are_exact_tile_ratio():
    panels = _far_pair()
    kfs = [_stack_kf(i * 0.5, panels) for i in range(4)]
    segs = build_render_segments(_traj(kfs), clip_duration=6.0)
    tile_ratio = 1920 / (1080 // 2)  # source-relative tile; box uses target 1080x1920
    # the panels target the DELIVERY tile ratio (1080:960), not the source ratio
    delivery_tile_ratio = 1080 / (1920 // 2)
    del tile_ratio
    for p in segs[0].box.panels:
        assert abs(p.w / p.h - delivery_tile_ratio) < 0.02
