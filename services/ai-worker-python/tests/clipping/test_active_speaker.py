"""active_speaker — pure ASD speaking helpers (REFRAME Phase 4)."""

from fliphouse_worker.clipping.active_speaker import (
    SPEAKING_ENTER,
    SPEAKING_EXIT,
    SPEAKING_THRESHOLD,
    SpeakerState,
    has_speaking_signal,
    max_co_present_faces,
    pick_active_speaker,
    pick_active_speaker_hyst,
    speaking_candidates,
)
from fliphouse_worker.clipping.crop_geometry import FaceBox


def _face(center_x: float, speaking: float | None) -> FaceBox:
    return FaceBox(x=center_x - 40, y=0.0, w=80.0, h=80.0, score=0.9, speaking=speaking)


def test_has_speaking_signal_true_when_any_scored():
    assert has_speaking_signal([_face(100.0, None), _face(200.0, 0.0)]) is True


def test_has_speaking_signal_false_when_all_none():
    assert has_speaking_signal([_face(100.0, None), _face(200.0, None)]) is False


def test_has_speaking_signal_false_when_empty():
    assert has_speaking_signal([]) is False


def test_speaking_candidates_ranks_loudest_first():
    quiet = _face(100.0, 0.6)
    loud = _face(200.0, 0.95)
    assert speaking_candidates([quiet, loud]) == [loud, quiet]


def test_speaking_candidates_excludes_sub_threshold_and_none():
    below = _face(100.0, SPEAKING_THRESHOLD - 0.01)
    unscored = _face(200.0, None)
    assert speaking_candidates([below, unscored]) == []


def test_pick_active_speaker_returns_loudest():
    a = _face(100.0, 0.7)
    b = _face(200.0, 0.9)
    assert pick_active_speaker([a, b]) is b


def test_pick_active_speaker_none_when_nobody_speaks():
    assert pick_active_speaker([_face(100.0, 0.1), _face(200.0, None)]) is None


def test_max_co_present_faces_returns_peak_over_frames():
    frames = (
        (_face(100.0, None),),
        (_face(100.0, None), _face(200.0, None), _face(300.0, None)),
        (),
    )
    assert max_co_present_faces(frames) == 3


def test_max_co_present_faces_zero_for_empty_clip():
    assert max_co_present_faces(()) == 0


def test_max_co_present_faces_zero_when_every_frame_faceless():
    assert max_co_present_faces(((), (), ())) == 0


def test_max_co_present_faces_one_for_single_face_clip():
    frames = ((_face(100.0, None),), (_face(120.0, None),))
    assert max_co_present_faces(frames) == 1


# --- P3-C2: hysteretic (dual-threshold + identity-hold) speaker pick -------------------


def test_hyst_acquires_loudest_over_enter():
    a = _face(100.0, 0.6)
    b = _face(900.0, 0.95)
    chosen, state = pick_active_speaker_hyst([a, b], SpeakerState())
    assert chosen is b
    assert state == SpeakerState(prev_center_x=900.0, is_speaker=True)


def test_hyst_acquires_nobody_when_all_below_enter():
    # The cross-talk band: 0.52/0.48 — neither clears ENTER=0.55 from a cold state, so
    # NOBODY is acquired and the caller rests on frontal-largest (no flip).
    a = _face(100.0, 0.52)
    b = _face(900.0, 0.48)
    chosen, state = pick_active_speaker_hyst([a, b], SpeakerState())
    assert chosen is None
    assert state == SpeakerState(prev_center_x=None, is_speaker=False)


def test_hyst_cross_talk_sequence_never_flips():
    # Alternating 0.52/0.48 between two heads over many frames acquires nobody every frame
    # (the A1 oscillation cause) — a single stable "no speaker" verdict, not a swap.
    state = SpeakerState()
    picks = []
    for left, right in [(0.52, 0.48), (0.48, 0.52), (0.53, 0.47), (0.49, 0.51)]:
        chosen, state = pick_active_speaker_hyst([_face(100.0, left), _face(900.0, right)], state)
        picks.append(chosen)
    assert picks == [None, None, None, None]


def test_hyst_holds_previous_speaker_lingering_in_band():
    # Acquire a clear talker, then it drops into the band (0.45 ∈ (EXIT, ENTER)) → HELD.
    a = _face(100.0, 0.9)
    chosen, state = pick_active_speaker_hyst([a], SpeakerState())
    assert chosen is a and state.is_speaker
    faded = _face(110.0, 0.45)
    held, state = pick_active_speaker_hyst([faded], state)
    assert held is faded and state.is_speaker  # kept while lingering above EXIT


def test_hyst_releases_speaker_below_exit():
    state = SpeakerState(prev_center_x=100.0, is_speaker=True)
    gone = _face(100.0, 0.30)  # below EXIT=0.40
    chosen, state = pick_active_speaker_hyst([gone], state)
    assert chosen is None
    assert state == SpeakerState(prev_center_x=None, is_speaker=False)


def test_hyst_hold_identifies_speaker_by_nearest_centre():
    # Two band-level faces while a speaker is held near x=100: the nearest-centre one is
    # kept (same person continuing), not the louder far one.
    state = SpeakerState(prev_center_x=100.0, is_speaker=True)
    near = _face(120.0, 0.42)
    far_louder = _face(900.0, 0.50)
    chosen, _ = pick_active_speaker_hyst([near, far_louder], state)
    assert chosen is near


def test_hyst_clear_challenger_switches_immediately():
    # A held speaker is overridden the instant a different face clears ENTER (1-sample
    # acquire latency — the loud branch wins regardless of held identity).
    state = SpeakerState(prev_center_x=100.0, is_speaker=True)
    challenger = _face(900.0, 0.92)
    chosen, state = pick_active_speaker_hyst([_face(110.0, 0.45), challenger], state)
    assert chosen is challenger
    assert state.prev_center_x == 900.0


def test_hyst_ignores_faces_without_speaking_score():
    # A landmark/ASD-less frame (all speaking=None) acquires nobody and stays released.
    chosen, state = pick_active_speaker_hyst(
        [_face(100.0, None), _face(900.0, None)], SpeakerState()
    )
    assert chosen is None
    assert state == SpeakerState(prev_center_x=None, is_speaker=False)


def test_hyst_collapses_to_stateless_pick_when_enter_equals_exit():
    # COLLAPSE PROPERTY: with enter==exit==SPEAKING_THRESHOLD the band is empty, so the
    # hold branch can never fire and the pick is byte-identical to pick_active_speaker
    # across an oscillating sequence (the byte-identity guarantee for valid inputs).
    frames = [
        [_face(100.0, 0.52), _face(900.0, 0.48)],
        [_face(100.0, 0.48), _face(900.0, 0.52)],
        [_face(100.0, 0.9), _face(900.0, 0.1)],
        [_face(100.0, 0.2), _face(900.0, None)],
    ]
    state = SpeakerState()
    for faces in frames:
        chosen, state = pick_active_speaker_hyst(
            faces, state, enter=SPEAKING_THRESHOLD, exit_thresh=SPEAKING_THRESHOLD
        )
        assert chosen is pick_active_speaker(faces)


def test_enter_is_above_exit():
    assert SPEAKING_ENTER > SPEAKING_EXIT  # a real Schmitt band exists by default


def test_hyst_rejects_inverted_thresholds():
    import pytest

    with pytest.raises(ValueError, match="must be >= exit_thresh"):
        pick_active_speaker_hyst([_face(100.0, 0.9)], SpeakerState(), enter=0.4, exit_thresh=0.55)


def test_speaker_state_rejects_speaker_without_centre():
    import pytest

    with pytest.raises(ValueError, match="requires a prev_center_x"):
        SpeakerState(prev_center_x=None, is_speaker=True)
