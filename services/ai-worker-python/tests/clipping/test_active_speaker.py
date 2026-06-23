"""active_speaker — pure ASD speaking helpers (REFRAME Phase 4)."""

from fliphouse_worker.clipping.active_speaker import (
    SPEAKING_THRESHOLD,
    has_speaking_signal,
    max_co_present_faces,
    pick_active_speaker,
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
