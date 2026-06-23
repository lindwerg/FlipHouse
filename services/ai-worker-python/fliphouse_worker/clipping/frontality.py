"""Pure frontality scoring from YuNet's 5 facial landmarks (P2 reframe; profile-aware).

YuNet (``cv2.FaceDetectorYN``) returns, per detection, a bounding box plus FIVE
landmarks in source pixels: right eye, left eye, nose tip, right mouth corner,
left mouth corner. From those points we score how FRONTAL the face is — a head
turned to camera (both eyes visible, nose centred between them) scores ~1.0; a
profile / back-of-head (one eye hidden, nose shoved to one side) scores ~0.0.

This is the signal the active-face selection uses to PREFER a frontal speaker over
a larger turned/profile head (founder complaint 3: the crop punched into a person
turned away instead of the one facing camera).

MediaPipe BlazeFace boxes carry NO landmarks; their frontality is reported as
``None`` (unknown) so the selection logic degrades to the legacy largest-face
heuristic for that provider — exactly the GigaAM→whisper provider-seam pattern.

Everything here is pure float math on a frozen 5-tuple of points, fully unit-tested
with synthetic landmark sets (no real cv2/onnx).
"""

from __future__ import annotations

# A face is considered "facing the camera" at/above this frontality score. Used by
# the active-face selection to split FRONTAL candidates from turned/profile ones.
FRONTAL_THRESHOLD: float = 0.55

# Frontality blends two independent symmetry cues, weighted so neither alone can
# call a clear profile "frontal":
#   * EYE balance — the nose's horizontal offset from the eye midpoint, relative to
#     the inter-eye span. A centred nose ⇒ frontal; a nose shoved past one eye ⇒
#     profile. This is the dominant cue.
#   * MOUTH balance — the same offset measured on the mouth corners, a weaker
#     corroborating cue (mouth corners collapse together in deep profile).
EYE_BALANCE_WEIGHT: float = 0.7
MOUTH_BALANCE_WEIGHT: float = 0.3

# Landmark indices in YuNet's 5-point layout (OpenCV Zoo YuNet 2023mar order).
RIGHT_EYE: int = 0
LEFT_EYE: int = 1
NOSE: int = 2
RIGHT_MOUTH: int = 3
LEFT_MOUTH: int = 4

Point = tuple[float, float]
Landmarks = tuple[Point, Point, Point, Point, Point]


def _balance(left_x: float, right_x: float, mid_x: float) -> float:
    """Symmetry of ``mid_x`` between ``left_x`` and ``right_x``, in ``[0, 1]``.

    1.0 when ``mid_x`` sits exactly halfway between the two outer points (perfectly
    symmetric ⇒ frontal); 0.0 when it has drifted to or past either outer point
    (a turned head whose nose/mouth has slid to one side ⇒ profile). Degenerate
    when the outer points coincide (the face is edge-on / zero inter-feature span),
    which reads as a profile ⇒ 0.0.
    """
    span = abs(right_x - left_x)
    if span <= 0.0:
        return 0.0
    centre = (left_x + right_x) / 2.0
    offset = abs(mid_x - centre)
    # offset == 0 → perfectly centred (1.0); offset == span/2 → at an outer point (0.0).
    return max(0.0, 1.0 - offset / (span / 2.0))


def frontality(landmarks: Landmarks) -> float:
    """Frontality score in ``[0, 1]`` from YuNet's 5 landmarks (1 = facing camera).

    PURE. Blends the eye-balance cue (nose centred between the eyes) with the
    weaker mouth-balance cue (nose centred between the mouth corners), so a clear
    profile — one eye hidden, nose past the other — scores low and a head-on face
    scores ~1.0. Robust to the face's screen position (it measures only RELATIVE
    landmark geometry, never absolute pixels).
    """
    re_x = landmarks[RIGHT_EYE][0]
    le_x = landmarks[LEFT_EYE][0]
    nose_x = landmarks[NOSE][0]
    rm_x = landmarks[RIGHT_MOUTH][0]
    lm_x = landmarks[LEFT_MOUTH][0]
    eye_balance = _balance(re_x, le_x, nose_x)
    mouth_balance = _balance(rm_x, lm_x, nose_x)
    return EYE_BALANCE_WEIGHT * eye_balance + MOUTH_BALANCE_WEIGHT * mouth_balance


def is_frontal(score: float | None) -> bool:
    """True when a face's frontality ``score`` clears :data:`FRONTAL_THRESHOLD`.

    An unknown score (``None`` — e.g. a MediaPipe box with no landmarks) is NOT
    treated as frontal: callers that want frontal-vs-turned discrimination fall back
    to their legacy heuristic when the provider gives no landmarks, rather than
    silently assuming every face is head-on.
    """
    return score is not None and score >= FRONTAL_THRESHOLD
