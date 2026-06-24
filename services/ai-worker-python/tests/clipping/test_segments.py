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
        _track(6, cx=960.0)  # idx 0..5  t=0.0..2.5  → TRACK crop
        + _general(3, start_idx=6)  # idx 6..8  t=3.0..4.0 → GENERAL full-frame CONTAIN
        + _track(3, cx=500.0, start_idx=9)  # idx 9..11 t=4.5..5.5 → TRACK crop again
    )


# Scene cuts that delimit the three vote-BLOCKS of ``_three_segment_traj`` (the non-causal
# mode timeline votes per scene-cut block, so a TRACK→GENERAL→TRACK shape needs a cut in each
# transition window to be three runs). 2.75 splits idx5(2.5)→idx6(3.0); 4.25 splits
# idx8(4.0)→idx9(4.5). Without these the whole clip is one block and votes a single mode.
_THREE_SEG_CUTS: tuple[float, ...] = (2.75, 4.25)


# ── resolve_mode_timeline ──────────────────────────────────────────────────


def test_timeline_empty_is_empty():
    assert resolve_mode_timeline(()) == ()


def test_timeline_pure_track_is_all_crop():
    modes = resolve_mode_timeline(_track(3))
    assert modes == (CROP_MODE, CROP_MODE, CROP_MODE)  # no spurious center-crop opening


def test_timeline_pure_general_is_all_blurpad():
    modes = resolve_mode_timeline(_general(3))
    assert modes == (BLURPAD_MODE, BLURPAD_MODE, BLURPAD_MODE)


def test_timeline_single_general_in_track_block_is_outvoted_all_crop():
    # one dropped face inside a tracked block is a minority → majority CROP everywhere
    kfs = _track(3) + _general(1, start_idx=3) + _track(3, start_idx=4)
    assert set(resolve_mode_timeline(kfs)) == {CROP_MODE}


def test_timeline_general_majority_block_votes_general_throughout():
    # 2 TRACK head + 3 GENERAL with NO cut → one block, GENERAL majority → ALL blurpad.
    # This kills the start-of-clip transient: the leading TRACK pair can't open the clip.
    kfs = _track(2) + _general(3, start_idx=2)
    modes = resolve_mode_timeline(kfs)
    assert set(modes) == {BLURPAD_MODE}  # whole block votes GENERAL — no leading CROP run


def test_timeline_tie_breaks_toward_crop():
    # 2 GENERAL + 2 TRACK, no cut → a 50/50 tie → tie-break is CROP (speaker default),
    # so the clip OPENS on the speaker crop (no GENERAL intro flash).
    kfs = _general(2) + _track(2, start_idx=2)
    modes = resolve_mode_timeline(kfs)
    assert set(modes) == {CROP_MODE}


def test_timeline_track_head_then_general_opens_general_case_a():
    # Case (a) "скачет": a 3-sample transient TRACK head of a genuine b-roll clip is
    # outvoted by the GENERAL majority → the clip OPENS wide, no ~1.5s crop→wide flip.
    kfs = _track(3) + _general(6, start_idx=3)
    modes = resolve_mode_timeline(kfs)
    assert set(modes) == {BLURPAD_MODE}


def test_timeline_general_head_then_track_opens_crop_case_b():
    # Case (b) "скачет": a 2-sample GENERAL head of a talking-head clip is outvoted by
    # the TRACK majority → the clip OPENS on the speaker crop, no ~0.75s wide→crop flip.
    kfs = _general(2) + _track(6, start_idx=2)
    modes = resolve_mode_timeline(kfs)
    assert set(modes) == {CROP_MODE}


def test_timeline_real_scene_cut_splits_blocks_independently():
    # A genuine cut at t=3.0 between a TRACK block and a GENERAL block: each block votes
    # on its OWN samples → the transition is preserved (not over-smoothed across the cut).
    kfs = _track(6) + _general(6, start_idx=6)  # cut falls at idx5(t=2.5)→idx6(t=3.0)
    modes = resolve_mode_timeline(kfs, scene_cut_times=(3.0,))
    assert set(modes[:6]) == {CROP_MODE}
    assert set(modes[6:]) == {BLURPAD_MODE}


def test_timeline_without_cut_one_block_majority_overrides_transition():
    # SAME samples as above but NO cut → one block; the 6/6 tie breaks toward CROP, so
    # there is NO mid-clip flip — a real transition needs a real cut to delimit a block.
    kfs = _track(6) + _general(6, start_idx=6)
    modes = resolve_mode_timeline(kfs)
    assert set(modes) == {CROP_MODE}


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
    segs = build_render_segments(
        _three_segment_traj(), clip_duration=6.0, scene_cut_times=_THREE_SEG_CUTS
    )
    assert [s.box.mode for s in segs] == [CROP_MODE, CROP_MODE, CROP_MODE]  # all fill-crops
    # contiguous, full coverage [0, clip_duration]
    assert segs[0].start_s == 0.0 and segs[-1].end_s == 6.0
    for a, b in zip(segs, segs[1:], strict=False):
        assert a.end_s == b.start_s


def test_track_general_track_columns_track_their_centers():
    segs = build_render_segments(
        _three_segment_traj(), clip_duration=6.0, scene_cut_times=_THREE_SEG_CUTS
    )
    centered = compute_crop_box(1920, 1080, center_x=None).x
    assert segs[0].box.x == centered  # speaker centered on 960 ≈ frame center
    # GENERAL/b-roll run → full-frame CONTAIN (whole frame in), not a center column.
    assert segs[1].box.layout == CONTAIN_LAYOUT
    assert (segs[1].box.x, segs[1].box.w) == (0, 1920)
    assert segs[2].box.layout == SINGLE_LAYOUT
    assert segs[2].box.x != centered  # speaker@500 shifts the crop column left


def test_scene_cut_in_transition_snaps_boundary_to_cut():
    # The cuts that delimit the vote-blocks ALSO position the run boundaries: the
    # TRACK→GENERAL flip lands exactly on the cut at 2.75 (the visible shot edge), not the
    # sample midpoint. (The non-causal vote splits blocks on the SAME cut predicate, so the
    # boundary and the block edge always agree.)
    segs = build_render_segments(
        _three_segment_traj(), clip_duration=6.0, scene_cut_times=_THREE_SEG_CUTS
    )
    assert segs[0].end_s == 2.75


def test_micro_segment_is_merged_then_neighbours_coalesce():
    # The middle GENERAL run (1.5s) is below the floor → merged into the previous CROP run;
    # the two CROP runs it sat between then COALESCE into one segment (same-mode walk). A
    # floor between the middle span (1.5) and the trailing span (1.75) catches ONLY the
    # middle, so the coalesce path (not a cascade) is what collapses to one segment.
    segs = build_render_segments(
        _three_segment_traj(), clip_duration=6.0, scene_cut_times=_THREE_SEG_CUTS, min_segment_s=1.6
    )
    assert len(segs) == 1 and segs[0].box.mode == CROP_MODE
    assert (segs[0].start_s, segs[0].end_s) == (0.0, 6.0)


def test_merge_short_absorbs_a_first_segment_above_the_opening_floor():
    # The opening guard only fires below OPENING_MIN_SEGMENT_S (1.5s). A first segment that
    # is LONGER than that but still below ``min_segment_s`` is absorbed by ``_merge_short``'s
    # own idx==0 path (the second segment's start backfilled to 0.0). Block A is a 1.75s
    # TRACK run (cut at 1.75) → above the opening floor, below the 2.5s merge floor.
    kfs = _track(4, cx=960.0) + _general(4, start_idx=4)  # cut at idx3(1.5)→idx4(2.0)
    segs = build_render_segments(
        _traj(kfs), clip_duration=6.0, scene_cut_times=(1.75,), min_segment_s=2.5
    )
    assert len(segs) == 1  # the 1.75s opening TRACK merged forward into the GENERAL run
    assert segs[0].start_s == 0.0


def test_merge_short_coalesce_walks_past_a_differing_pair():
    # Four blocks CROP/BLURPAD/CROP/BLURPAD with a SHORT 3rd block. Merging the short 3rd
    # into the 2nd leaves CROP, BLURPAD, BLURPAD — the coalesce loop walks PAST the leading
    # differing CROP/BLURPAD pair (the i+=1 step) before joining the trailing same-mode pair.
    kfs = (
        _track(4, cx=960.0)  # block A  idx0..3  t=0.0..1.5  CROP
        + _general(4, start_idx=4)  # block B  idx4..7  t=2.0..3.5  BLURPAD
        + _track(2, cx=500.0, start_idx=8)  # block C  idx8..9  t=4.0..4.5  CROP (short)
        + _general(4, start_idx=10)  # block D  idx10..13 t=5.0..6.5  BLURPAD
    )
    # cuts delimit each block transition: 1.75 (A→B), 3.75 (B→C), 4.75 (C→D)
    segs = build_render_segments(
        _traj(kfs), clip_duration=7.0, scene_cut_times=(1.75, 3.75, 4.75), min_segment_s=1.5
    )
    # block C ([3.75, 4.75], span 1.0 < 1.5) is merged into B → B+C coalesce; the result is
    # three segments CROP / BLURPAD / BLURPAD-trailing collapsed: CROP, BLURPAD.
    assert [s.box.layout for s in segs] == ["SINGLE", "CONTAIN"]
    assert segs[0].start_s == 0.0 and segs[-1].end_s == 7.0


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


def test_short_first_segment_merges_forward_into_next():
    # A genuine short GENERAL cold-open block (1.0s) before a cut, then a long TRACK block.
    # The opening block is shorter than OPENING_MIN_SEGMENT_S and differs from the next →
    # absorbed forward, so the clip OPENS on the dominant TRACK framing (no opening flash).
    kfs = _general(2) + _track(6, start_idx=2)  # cut at idx1(0.5)→idx2(1.0)
    segs = build_render_segments(_traj(kfs), clip_duration=8.0, scene_cut_times=(1.0,))
    assert len(segs) == 1
    assert segs[0].box.mode == CROP_MODE and segs[0].box.layout == SINGLE_LAYOUT
    assert segs[0].start_s == 0.0  # short opening GENERAL absorbed into the TRACK run


def test_short_first_segment_backfill_then_coalesce_walks():
    # Opening short GENERAL block, a long TRACK block, then a long GENERAL block (3 blocks via
    # two cuts). The opening GENERAL is absorbed forward into TRACK; the coalesce pass then
    # walks past the differing TRACK/GENERAL pair without collapsing it → two segments.
    kfs = _general(2) + _track(6, start_idx=2) + _general(6, start_idx=8)
    segs = build_render_segments(
        _traj(kfs), clip_duration=8.0, scene_cut_times=(1.0, 4.0), min_segment_s=0.75
    )
    assert [s.box.mode for s in segs] == [CROP_MODE, CROP_MODE]
    assert segs[0].box.layout == SINGLE_LAYOUT  # opened on the dominant TRACK framing
    assert segs[1].box.layout == CONTAIN_LAYOUT  # the trailing b-roll block
    assert segs[0].start_s == 0.0


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
