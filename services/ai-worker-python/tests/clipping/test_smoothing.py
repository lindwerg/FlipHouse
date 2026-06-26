"""build_trajectory — deadband/One-Euro center, asymmetric zoom, scene-cut reset,
co-present union subject, faceless/edge/crowd GENERAL."""

from fliphouse_worker.clipping.crop_geometry import (
    CONTEXT_CONTAIN_MARK,
    GENERAL_MARK,
    TRACK_MARK,
    FaceBox,
)
from fliphouse_worker.clipping.smoothing import (
    ZOOM_IN_EASE,
    ZOOM_OUT_EASE,
    RawSample,
    _all_profile,
    _ease_zoom,
    _pick_dominant,
    _scaled_box,
    build_trajectory,
)

# A genuine CLOSE-UP face side (px): big enough that a centered subject does NOT trip
# ``needs_context`` (padded width ≥ CONTEXT_SUBJECT_FRAC of the 562px column at 1000-wide,
# and h ≥ CONTEXT_FACE_HEIGHT_FRAC·src_h at 1000-tall) — so the single-face machinery tests
# still exercise the TRACK speaker-crop path. Small faces are used explicitly where a test
# WANTS the cinematic-wide CONTEXT-CONTAIN escape.
_CLOSEUP_SIDE: float = 260.0


def _face(center_x: float, side: float = _CLOSEUP_SIDE) -> FaceBox:
    return FaceBox(x=center_x - side / 2.0, y=400.0, w=side, h=side, score=0.9)


def _frontal_landmarks(center_x: float):
    """Camera-facing 5-landmark set (nose centred between spread eyes)."""
    return (
        (center_x - 30.0, 400.0),
        (center_x + 30.0, 400.0),
        (center_x, 430.0),
        (center_x - 20.0, 450.0),
        (center_x + 20.0, 450.0),
    )


def _profile_landmarks(center_x: float):
    """Turned-away 5-landmark set (nose shoved past the eyes)."""
    return (
        (center_x - 5.0, 400.0),
        (center_x + 5.0, 400.0),
        (center_x + 40.0, 430.0),
        (center_x - 3.0, 450.0),
        (center_x + 3.0, 450.0),
    )


def _frontal_face(center_x: float, side: float = 100.0) -> FaceBox:
    return FaceBox(
        x=center_x - side / 2.0,
        y=400.0,
        w=side,
        h=side,
        score=0.9,
        landmarks=_frontal_landmarks(center_x),
    )


def _profile_face(center_x: float, side: float = 100.0) -> FaceBox:
    return FaceBox(
        x=center_x - side / 2.0,
        y=400.0,
        w=side,
        h=side,
        score=0.9,
        landmarks=_profile_landmarks(center_x),
    )


def _single(t: float, center_x: float, side: float = _CLOSEUP_SIDE) -> RawSample:
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
    # A close-up off-center but NOT clipping the column (1400 of 1920, side 340 → stays
    # TRACK): the first euro sample passes the center through unchanged.
    samples = [_single(0.0, 1400.0, side=340.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[0].center_x == 1400.0  # first euro sample passes through


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


def test_far_apart_co_present_follows_dominant_close_up_face_not_union():
    # Heads SO far apart that even the WIDEST 9:16 cannot hold both: keeping both would
    # stretch or show the empty gap, so the subject is the DOMINANT (larger) face. The
    # dominant is a near-center CLOSE-UP (h ≥ floor, padded ≥ 0.55·column, not clipping),
    # so it does NOT trip ``needs_context`` → punch into it (TRACK), not CONTEXT-CONTAIN.
    small = FaceBox(x=15.0, y=400.0, w=90.0, h=90.0, score=0.9)  # extreme-left tiny head
    big = FaceBox(x=340.0, y=300.0, w=320.0, h=320.0, score=0.9)  # near-center close-up @500
    samples = [RawSample(0.0, 60.0, 2, face=small, faces=(small, big))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.face.center_x == big.center_x  # the larger head


def test_far_apart_dominant_small_head_in_wide_scene_escapes_to_context_contain():
    # NEW (founder: "сбоку не входит"): the same far-apart-pair geometry, but the dominant
    # head is SMALL relative to the frame (a wide/establishing 2-shot). Punching the 608px
    # column onto it would slice the scene, so the lone dominant head re-applies
    # ``needs_context`` and escapes to CONTEXT-CONTAIN (full-frame, scene kept).
    small = FaceBox(x=80.0, y=400.0, w=90.0, h=90.0, score=0.9)
    big = FaceBox(x=820.0, y=400.0, w=160.0, h=160.0, score=0.9)  # only 16% of src height
    samples = [RawSample(0.0, 125.0, 2, face=small, faces=(small, big))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == CONTEXT_CONTAIN_MARK  # wide scene kept, not a 608px punch
    assert kf.face is None and kf.center_x is None  # CONTEXT-CONTAIN carries no column


def test_far_apart_punches_into_the_frontal_close_up_not_the_larger_profile():
    # Two heads too far apart for one 9:16. The SMALLER one faces the camera (a near-center
    # CLOSE-UP so it stays TRACK), the LARGER is turned away → punch into the FRONTAL
    # speaker, never the bigger profile. (Frontal-first beats largest in ``_pick_dominant``.)
    small_frontal = FaceBox(
        x=340.0, y=300.0, w=320.0, h=320.0, score=0.9, landmarks=_frontal_landmarks(500.0)
    )
    big_profile = FaceBox(
        x=930.0, y=400.0, w=170.0, h=170.0, score=0.9, landmarks=_profile_landmarks(1015.0)
    )
    samples = [RawSample(0.0, 500.0, 2, face=small_frontal, faces=(small_frontal, big_profile))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1200, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.face.center_x == small_frontal.center_x


def test_far_apart_only_profiles_escapes_to_context_contain_not_a_punch_in():
    # Founder complaint 3 + "сбоку не входит": nobody faces the camera (both profiles) and
    # they are SO far apart even the WIDEST 9:16 cannot hold both. A single SINGLE crop of
    # the wide union would slice one head out, so we keep the WHOLE scene via CONTEXT-CONTAIN
    # (full-frame fit) rather than punch into a side/back-of-head. (Union 1650px >> widest
    # 9:16 607.5, so the union-fit branches fail and we reach the all-profiles fallback.)
    left = _profile_face(200.0, 150.0)
    right = _profile_face(1700.0, 150.0)
    samples = [RawSample(0.0, 200.0, 2, face=left, faces=(left, right))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    kf = traj.keyframes[0]
    assert kf.mode == CONTEXT_CONTAIN_MARK  # both profiles kept in the full-frame scene
    assert kf.face is None and kf.center_x is None


def test_all_profile_is_false_for_fewer_than_two_faces():
    # A single profile is NOT an "only-profiles 2-shot" — there is no second head to
    # keep, so the wide-framing fallback never triggers for one face.
    assert _all_profile(()) is False
    assert _all_profile((_profile_face(500.0, 100.0),)) is False
    # Two profiles with real low-frontality landmarks → only-profiles.
    assert _all_profile((_profile_face(200.0), _profile_face(800.0))) is True
    # A landmark-less (MediaPipe) box never counts as a known profile.
    assert _all_profile((_face(200.0), _face(800.0))) is False


def test_pick_dominant_is_none_for_empty_faces():
    assert _pick_dominant(()) is None


def _speaking(face: FaceBox, score: float) -> FaceBox:
    """Re-stamp ``face`` with an ASD speaking score (frozen → new instance)."""
    return FaceBox(
        x=face.x,
        y=face.y,
        w=face.w,
        h=face.h,
        score=face.score,
        landmarks=face.landmarks,
        speaking=score,
    )


def test_pick_dominant_follows_asd_speaker_over_larger_silent_head():
    # REFRAME Phase 4: the GPU lane marks the SMALLER head as the talker → punch into
    # the speaker, overriding the larger silent head (profile/who-to-follow fix).
    small_talker = _speaking(_face(200.0, 90.0), 0.95)
    big_silent = _speaking(_face(820.0, 160.0), 0.02)
    assert _pick_dominant((small_talker, big_silent)) is small_talker


def test_all_profile_false_when_an_asd_speaker_is_present():
    # Two profiles, but the GPU lane found a talker → do NOT stay wide; the caller
    # punches into the speaker instead of keeping the 2-shot.
    left = _speaking(_profile_face(200.0), 0.9)
    right = _speaking(_profile_face(800.0), 0.05)
    assert _all_profile((left, right)) is False


def test_far_apart_only_profiles_with_speaker_punches_into_the_talker():
    # End-to-end: two far-apart profiles where the WIDEST 9:16 cannot hold both, but ASD
    # flags the LEFT one as the speaker → the crop follows the talker, not the gap. The
    # talker is a near-center CLOSE-UP (does not trip ``needs_context``), so the column
    # genuinely frames it → TRACK. ASD scopes to centering; width stays geometric.
    left = _speaking(_profile_face(600.0, 360.0), 0.95)
    right = _speaking(_profile_face(1750.0, 120.0), 0.03)
    samples = [RawSample(0.0, 600.0, 2, face=left, faces=(left, right))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.face.center_x == left.center_x


def test_far_apart_both_frontal_splits_into_a_stack_keeping_both():
    # Both face the camera but can't share one 9:16 → SPLIT-SCREEN STACK: each speaker
    # gets their own panel (both kept full-size), never a punch-in onto the larger head.
    small = FaceBox(x=80.0, y=400.0, w=90.0, h=90.0, score=0.9, landmarks=_frontal_landmarks(125.0))
    big = FaceBox(
        x=820.0, y=400.0, w=160.0, h=160.0, score=0.9, landmarks=_frontal_landmarks(900.0)
    )
    samples = [RawSample(0.0, 125.0, 2, face=small, faces=(small, big))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    # The keyframe carries BOTH per-speaker panel faces (the union stays in ``face``).
    assert {f.center_x for f in kf.panels} == {small.center_x, big.center_x}
    # union spans 80..980 → center 530 (kept for the run's center/zoom bookkeeping)
    assert kf.face is not None and kf.face.center_x == 530.0


def test_cross_talk_band_does_not_flip_the_punched_speaker():
    # P3-C2 end-to-end: two FAR-APART heads (the widest 9:16 cannot hold both → a single
    # head is punched) whose ASD scores oscillate inside the (EXIT, ENTER) cross-talk band
    # (0.52/0.48 alternating). Pre-C2 the stateless 0.5 threshold flipped the punch between
    # the two heads every frame (the ~950px swing). Post-C2 NOBODY clears ENTER, so no
    # speaker is acquired and the punch rests on the stable frontal/largest head — the
    # emitted subject centre never jumps to the small far head.
    big_left_cx, small_right_cx = 600.0, 1750.0
    samples = []
    for i, (left_s, right_s) in enumerate([(0.52, 0.48), (0.48, 0.52), (0.53, 0.47)]):
        left = _speaking(_face(big_left_cx, 360.0), left_s)
        right = _speaking(_face(small_right_cx, 120.0), right_s)
        samples.append(RawSample(i * 0.5, big_left_cx, 2, face=left, faces=(left, right)))
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    tracks = [kf for kf in traj.keyframes if kf.mode == TRACK_MARK]
    assert len(tracks) == 3  # every frame punches a single head (no CONTAIN/STACK here)
    # The punched head is ALWAYS the larger left one — never the small far-right talker.
    assert all(kf.face is not None and kf.face.center_x == big_left_cx for kf in tracks)


def test_held_speaker_does_not_bleed_across_a_scene_cut():
    # P3-C2 regression guard: a speaker held at the end of shot 1 must NOT carry its
    # identity into shot 2. Shot 1 acquires a clear talker at x=1500 (profile). After the
    # cut, shot 2 has two far-apart BAND faces (both 0.45 ∈ band): a profile at x=1500 and
    # a FRONTAL head at x=400. Without the cut reset the leaked HOLD would lock the stale
    # x=1500 profile (founder complaint 3); with the reset shot 2 re-acquires cold → no
    # speaker → frontal-largest picks the FRONTAL x=400 head.
    shot1 = _speaking(_profile_face(1500.0, 360.0), 0.90)
    p_profile = _speaking(_profile_face(1500.0, 400.0), 0.45)
    q_frontal = _speaking(_frontal_face(400.0, 400.0), 0.45)
    samples = [
        RawSample(0.0, 1500.0, 1, face=shot1, faces=(shot1,)),
        RawSample(1.0, 400.0, 2, face=q_frontal, faces=(p_profile, q_frontal)),
    ]
    traj = build_trajectory(samples, scene_cut_times=[1.0], src_w=1920, src_h=1080)
    post_cut = traj.keyframes[1]
    assert post_cut.mode == TRACK_MARK
    assert post_cut.face is not None and post_cut.face.center_x == 400.0  # frontal Q, not 1500


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
    # A centered close-up (stays TRACK) bracketing a faceless GENERAL frame: the tracked
    # centre survives the gap (the held center is not reset without a scene cut).
    samples = [_single(0.0, 500.0), RawSample(0.5, None, 0), _single(1.0, 500.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    tracks = [kf.center_x for kf in traj.keyframes if kf.mode == TRACK_MARK]
    assert tracks == [500.0, 500.0]  # centre survives the GENERAL sample between


def test_face_near_frame_edge_marks_general():
    # A single face within the 10% edge margin (leaving frame into b-roll) → whole frame.
    samples = [_single(0.0, 50.0)]  # centre at 5% of width
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == GENERAL_MARK


def test_single_small_face_in_wide_shot_escapes_to_context_contain():
    # THE founder fix ("сбоку не входит"): a single subject SMALL relative to a cinematic-WIDE
    # 1920×1080 frame (a man driving with scene context) would be punched into a 608px column
    # that slices the scene — instead it escapes to CONTEXT-CONTAIN (full-frame, scene kept).
    small = FaceBox(x=1200.0, y=460.0, w=150.0, h=150.0, score=0.9)  # 13.9% of 1080 height
    samples = [RawSample(0.0, small.center_x, 1, face=small, faces=(small,))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    kf = traj.keyframes[0]
    assert kf.mode == CONTEXT_CONTAIN_MARK
    assert kf.face is None and kf.center_x is None  # renders full-frame, no speaker column


def test_single_genuine_close_up_still_tracks_a_speaker_crop():
    # REGRESSION GUARD: a centered, frame-filling talking head does NOT escape to CONTAIN —
    # it still FILLs as a TRACK speaker crop (close-ups must not become letterboxed thumbnails).
    closeup = FaceBox(x=750.0, y=300.0, w=420.0, h=420.0, score=0.9)  # 38.9% of 1080, centered
    samples = [RawSample(0.0, closeup.center_x, 1, face=closeup, faces=(closeup,))]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    kf = traj.keyframes[0]
    assert kf.mode == TRACK_MARK
    assert kf.face is not None and kf.center_x == closeup.center_x


def test_context_contain_keyframe_does_not_count_as_a_track_center():
    # A clip of only cinematic-WIDE CONTEXT-CONTAIN samples carries no TRACK center → the
    # trajectory reports GENERAL-equivalent (no dominant speaker column to position).
    small = FaceBox(x=1200.0, y=460.0, w=150.0, h=150.0, score=0.9)
    samples = [RawSample(t, small.center_x, 1, face=small, faces=(small,)) for t in (0.0, 0.5, 1.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1920, src_h=1080)
    assert all(kf.mode == CONTEXT_CONTAIN_MARK for kf in traj.keyframes)
    assert traj.dominant_center() is None and traj.is_general() is True


def test_context_contain_at_scene_cut_resets_without_crashing():
    # A CONTEXT-CONTAIN sample landing ON a scene cut snaps the held center to the resolved
    # subject center (bookkeeping) and emits the CONTEXT-CONTAIN keyframe — no crash, no column.
    small = FaceBox(x=1200.0, y=460.0, w=150.0, h=150.0, score=0.9)
    closeup = FaceBox(x=750.0, y=300.0, w=420.0, h=420.0, score=0.9)  # centered close-up @960
    samples = [
        RawSample(0.0, closeup.center_x, 1, face=closeup, faces=(closeup,)),  # close-up TRACK
        RawSample(0.5, small.center_x, 1, face=small, faces=(small,)),  # wide → CONTEXT-CONTAIN
    ]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1920, src_h=1080)
    assert traj.keyframes[0].mode == TRACK_MARK
    assert traj.keyframes[1].mode == CONTEXT_CONTAIN_MARK


def test_track_keyframe_carries_scaled_subject_box():
    samples = [_single(0.0, 500.0)]
    traj = build_trajectory(samples, scene_cut_times=[], src_w=1000, src_h=1000)
    assert traj.keyframes[0].mode == TRACK_MARK
    # First (post-reset) zoom sample passes the height through unchanged (close-up side).
    assert traj.keyframes[0].face is not None
    assert traj.keyframes[0].face.h == _CLOSEUP_SIDE
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
    # Close-up faces (both above the CONTEXT-CONTAIN floor at 1000-wide so they stay TRACK
    # and exercise the ZOOM axis): the subject grows 320→520 (delta 200).
    small, big = _face(500.0, 320.0), _face(500.0, 520.0)
    grow = [RawSample(0.0, 500.0, 1, face=small, faces=(small,))]
    grow += [RawSample(0.5, 500.0, 1, face=big, faces=(big,))]
    traj_grow = build_trajectory(grow, scene_cut_times=[], src_w=1000, src_h=1000)
    # second sample: zoom-OUT toward 520 from 320 → fast ease closes most of the gap
    assert traj_grow.keyframes[1].face.h == 320.0 + ZOOM_OUT_EASE * 200.0


def test_scene_cut_hard_resets_zoom_axis():
    # Close-up faces (above the CONTEXT-CONTAIN floor → TRACK) so the ZOOM reset is visible.
    small, big = _face(500.0, 320.0), _face(500.0, 520.0)
    samples = [
        RawSample(0.0, 500.0, 1, face=small, faces=(small,)),
        RawSample(0.5, 500.0, 1, face=big, faces=(big,)),  # cut here → zoom passes through
    ]
    traj = build_trajectory(samples, scene_cut_times=[0.5], src_w=1000, src_h=1000)
    assert traj.keyframes[1].face.h == 520.0  # reset → no easing across the cut


def test_scaled_box_zero_height_returns_unchanged():
    degenerate = FaceBox(x=0.0, y=0.0, w=10.0, h=0.0, score=0.5)
    assert _scaled_box(degenerate, 50.0) is degenerate
