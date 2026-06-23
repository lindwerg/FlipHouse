"""Pure active-speaker helpers (REFRAME Phase 4; GPU LR-ASD lane).

The GPU lane (``services/gpu-asd`` — LR-ASD, MIT, bundled weights, NO pyannote)
returns a per-frame per-face SPEAKING confidence. We attach that confidence to the
:class:`FaceBox` as :attr:`FaceBox.speaking` and let it OVERRIDE the CPU
frontal-largest heuristic: the crop follows whoever is actually TALKING, not the
biggest frontal head.

This module is the pure decision layer — no network, no GPU, no cv2. It is
exercised 100% offline with hand-built :class:`FaceBox` values. The impure boundary
(the call to the gpu-asd endpoint) lives behind an injected transport in
``speaker_region.py``; here we only reason over faces that already carry a
``speaking`` score.

Why a SEPARATE override instead of folding into frontality: frontality is a static
pose cue (is this head facing the camera?), while speaking is a dynamic identity cue
(is this the person talking right now?). In the only-profiles case BOTH heads are
non-frontal, so frontality cannot disambiguate — but exactly one is speaking, so the
ASD score can. When ASD is present it is the STRONGER signal and wins outright; when
absent (``None``) every helper here is a no-op and the legacy heuristic stands.
"""

from __future__ import annotations

from collections.abc import Sequence

from .crop_geometry import FaceBox

# A face is treated as the active SPEAKER at/above this confidence. Tuned high so a
# faint cross-talk score never steals the crop from the dominant talker; below it the
# face is "not the speaker" and the legacy frontal-largest heuristic decides.
SPEAKING_THRESHOLD: float = 0.5


def has_speaking_signal(faces: Sequence[FaceBox]) -> bool:
    """True when ANY face in the frame carries a (non-None) ASD speaking score.

    The single gate the selection code uses to decide whether the ASD override is
    live for THIS frame. A frame the GPU lane did not score (or a CPU-only run) has
    every ``speaking`` as ``None`` → the legacy heuristic is used unchanged.
    """
    return any(f.speaking is not None for f in faces)


def speaking_candidates(faces: Sequence[FaceBox]) -> list[FaceBox]:
    """Faces talking at/above :data:`SPEAKING_THRESHOLD`, ranked loudest-first.

    Empty when no face clears the bar (everyone silent / only faint cross-talk), in
    which case callers fall back to their frontal-largest heuristic. A non-None but
    sub-threshold score is NOT a speaker. Ordering is by descending confidence so the
    first element is the clearest talker; ties keep input order (stable sort).
    """
    talking = [f for f in faces if f.speaking is not None and f.speaking >= SPEAKING_THRESHOLD]
    return sorted(talking, key=lambda f: f.speaking or 0.0, reverse=True)


def pick_active_speaker(faces: Sequence[FaceBox]) -> FaceBox | None:
    """The single clearest active speaker in the frame, or ``None`` if nobody talks.

    PURE. Returns the highest-confidence speaking face when at least one clears the
    threshold; ``None`` when no face is speaking (silent frame, or no ASD signal at
    all). This is the SUBJECT-override the crop follows: it beats frontal-largest
    whenever it resolves, so a smaller turned talker wins over a bigger silent head.
    """
    candidates = speaking_candidates(faces)
    return candidates[0] if candidates else None
