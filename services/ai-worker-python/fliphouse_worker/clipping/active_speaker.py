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
from dataclasses import dataclass

from .crop_geometry import FaceBox

# A face is treated as the active SPEAKER at/above this confidence. Tuned high so a
# faint cross-talk score never steals the crop from the dominant talker; below it the
# face is "not the speaker" and the legacy frontal-largest heuristic decides.
SPEAKING_THRESHOLD: float = 0.5

# P3-C2 — dual-threshold (Schmitt-trigger) for the HYSTERETIC speaker pick. A face must
# clear ENTER to ACQUIRE the speaker role; once acquired it is HELD while it stays above
# EXIT (the lower bar). The band (EXIT, ENTER) is the dead-zone: a cross-talk score that
# straddles it (e.g. 0.52/0.48 alternating between two heads) acquires NOBODY, so the crop
# rests on the stable frontal-largest pick instead of flipping every frame. Setting
# ENTER == EXIT collapses the trigger to the legacy single-threshold pick byte-for-byte.
SPEAKING_ENTER: float = 0.55
SPEAKING_EXIT: float = 0.40


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


def max_co_present_faces(frames: Sequence[Sequence[FaceBox]]) -> int:
    """The most faces visible in any single sampled frame across the clip.

    PURE. Drives the multi-face GATE in the GPU-ASD selector: only clips that ever show
    ``>= min_faces`` co-present faces pay the GPU tax, because active-speaker
    disambiguation only matters when two or more faces compete for the crop. A
    single-face (or faceless) clip is already solved by frontal-largest, so the GPU call
    is skipped. Returns 0 for an empty clip or a clip whose every frame is faceless.
    """
    return max((len(frame) for frame in frames), default=0)


def pick_active_speaker(faces: Sequence[FaceBox]) -> FaceBox | None:
    """The single clearest active speaker in the frame, or ``None`` if nobody talks.

    PURE. Returns the highest-confidence speaking face when at least one clears the
    threshold; ``None`` when no face is speaking (silent frame, or no ASD signal at
    all). This is the SUBJECT-override the crop follows: it beats frontal-largest
    whenever it resolves, so a smaller turned talker wins over a bigger silent head.
    """
    candidates = speaking_candidates(faces)
    return candidates[0] if candidates else None


@dataclass(frozen=True)
class SpeakerState:
    """Carried-forward identity for the hysteretic speaker pick (P3-C2).

    ``FaceBox`` carries no track id, so the held speaker's identity across frames is
    re-derived geometrically by nearest centre. ``prev_center_x`` is the held speaker's
    last centre (``None`` before anyone is acquired); ``is_speaker`` is whether a speaker
    is currently held. Immutable: each pick returns the next state.
    """

    prev_center_x: float | None = None
    is_speaker: bool = False

    def __post_init__(self) -> None:
        """A held speaker MUST carry the centre that identifies it next frame.

        The HOLD branch is gated on ``is_speaker and prev_center_x is not None``; a state
        claiming a speaker with no centre is a contradiction that would silently skip the
        hold, so it is rejected at construction instead of degrading quietly.
        """
        if self.is_speaker and self.prev_center_x is None:
            raise ValueError("is_speaker=True requires a prev_center_x")


def pick_active_speaker_hyst(
    faces: Sequence[FaceBox],
    state: SpeakerState,
    *,
    enter: float = SPEAKING_ENTER,
    exit_thresh: float = SPEAKING_EXIT,
) -> tuple[FaceBox | None, SpeakerState]:
    """Hysteretic active-speaker pick: ACQUIRE the loudest face over ``enter``, else HOLD
    the previous speaker (nearest centre) while it stays at/above ``exit_thresh``, else
    release.

    PURE. Returns ``(speaker | None, next_state)``. The dual threshold is a Schmitt
    trigger: a clear talker (``>= enter``) is taken immediately (1-sample acquire, and a
    louder challenger switches at once); when nobody is clearly speaking the previously
    held speaker is kept while it lingers in the band ``[exit_thresh, enter)``, identified
    as the nearest-centre speaking face to where it last was; a score below ``exit_thresh``
    releases it. A cross-talk pair straddling the band acquires nobody, so the caller rests
    on its stable frontal-largest pick instead of flipping.

    Collapse: with ``enter == exit_thresh`` the band is empty, so the HOLD branch can never
    fire (no face is simultaneously ``< enter`` and ``>= exit_thresh``) and the result is
    exactly the loudest face ``>= threshold`` — byte-identical to :func:`pick_active_speaker`.
    """
    if enter < exit_thresh:
        raise ValueError(f"enter ({enter}) must be >= exit_thresh ({exit_thresh})")
    scored = [f for f in faces if f.speaking is not None]
    loud = [f for f in scored if f.speaking >= enter]  # type: ignore[operator]
    if loud:
        # ACQUIRE / SWITCH: the clearest talker wins outright (loudest, stable tie order).
        chosen = max(loud, key=lambda f: f.speaking or 0.0)
        return chosen, SpeakerState(prev_center_x=chosen.center_x, is_speaker=True)
    if state.is_speaker and state.prev_center_x is not None:
        # HOLD: keep the same person (nearest centre) while they linger above EXIT.
        held_pool = [f for f in scored if f.speaking >= exit_thresh]  # type: ignore[operator]
        if held_pool:
            held = min(held_pool, key=lambda f: abs(f.center_x - state.prev_center_x))
            return held, SpeakerState(prev_center_x=held.center_x, is_speaker=True)
    # RELEASE: nobody is speaking clearly enough — fall back to frontal-largest.
    return None, SpeakerState(prev_center_x=None, is_speaker=False)
