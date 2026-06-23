"""frontality — pure 5-landmark frontality scoring (frontal vs profile), threshold gate.

Synthetic landmark sets only — never a real cv2/onnx detection. A FRONTAL face has
both eyes spread apart with the nose centred between them; a PROFILE has the nose
shoved past one eye (the far eye barely visible / collapsed toward the near one).
"""

from fliphouse_worker.clipping.frontality import (
    FRONTAL_THRESHOLD,
    frontality,
    is_frontal,
)


def _landmarks(re_x, le_x, nose_x, rm_x, lm_x, *, y=100.0):
    """Build a 5-tuple (right-eye, left-eye, nose, right-mouth, left-mouth) at row ``y``."""
    return (
        (re_x, y),
        (le_x, y),
        (nose_x, y + 30.0),
        (rm_x, y + 50.0),
        (lm_x, y + 50.0),
    )


def test_frontal_face_scores_near_one():
    # Eyes wide apart (400..600), nose dead-centre (500), mouth centred too → ~1.0.
    lm = _landmarks(re_x=400.0, le_x=600.0, nose_x=500.0, rm_x=440.0, lm_x=560.0)
    score = frontality(lm)
    assert score > 0.95
    assert is_frontal(score) is True


def test_profile_face_scores_low():
    # Head turned right: the left eye has slid almost onto the right eye and the nose
    # sits past them → a clear profile, well under the threshold.
    lm = _landmarks(re_x=500.0, le_x=520.0, nose_x=560.0, rm_x=505.0, lm_x=525.0)
    score = frontality(lm)
    assert score < FRONTAL_THRESHOLD
    assert is_frontal(score) is False


def test_three_quarter_face_between_frontal_and_profile():
    # A slight turn: nose offset from the eye midpoint but not past an eye → mid score,
    # strictly between a clean frontal and a clean profile.
    frontal = frontality(_landmarks(400.0, 600.0, 500.0, 440.0, 560.0))
    profile = frontality(_landmarks(500.0, 520.0, 560.0, 505.0, 525.0))
    three_quarter = frontality(_landmarks(400.0, 600.0, 560.0, 460.0, 580.0))
    assert profile < three_quarter < frontal


def test_balance_degenerates_to_profile_when_eyes_coincide():
    # Edge-on head: both eyes project to the same x (zero inter-eye span) → 0.0 cue.
    # With the mouth also collapsed, frontality is 0.0 (treated as a profile).
    lm = _landmarks(re_x=500.0, le_x=500.0, nose_x=500.0, rm_x=500.0, lm_x=500.0)
    assert frontality(lm) == 0.0
    assert is_frontal(frontality(lm)) is False


def test_nose_past_the_eye_clamps_to_zero_not_negative():
    # Nose shoved beyond the right eye (offset > half the inter-eye span): the cue
    # clamps at 0.0 rather than going negative, so the blended score stays in [0, 1].
    lm = _landmarks(re_x=400.0, le_x=600.0, nose_x=720.0, rm_x=440.0, lm_x=560.0)
    score = frontality(lm)
    assert 0.0 <= score <= 1.0
    assert score < FRONTAL_THRESHOLD


def test_is_frontal_none_is_not_frontal():
    # Unknown pose (a MediaPipe box with no landmarks) is NOT assumed frontal.
    assert is_frontal(None) is False


def test_is_frontal_boundary_is_inclusive():
    assert is_frontal(FRONTAL_THRESHOLD) is True
    assert is_frontal(FRONTAL_THRESHOLD - 0.01) is False
