"""Wire-contract dataclasses — the EXACT shapes shared with the worker's ASD seam.

The worker POSTs ``/score`` with a window of the source plus, per sampled frame, the
face boxes it already detected on CPU; this service runs LR-ASD over those tracks and
returns one SPEAKING score per (frame, face). The shapes here are the in-memory
mirror of that JSON; ``ScoreResponse.to_dict`` is the canonical body the app emits.
"""

from __future__ import annotations

from dataclasses import dataclass

ENGINE_LR_ASD = "lr-asd"


@dataclass(frozen=True)
class FaceRef:
    """One detected face box in source pixels (top-left origin) — the worker's box."""

    x: float
    y: float
    w: float
    h: float


@dataclass(frozen=True)
class ScoreRequest:
    """The validated ``/score`` body (worker → this service).

    ``frames`` is the per-sampled-frame list of face boxes (the same order the worker
    sampled); ``frames[i][j]`` is face ``j`` in frame ``i``. The response score grid
    MUST mirror this ragged shape exactly so the worker can zip scores back onto faces.
    """

    proxy_url: str
    start: float
    end: float
    sample_fps: float
    frames: tuple[tuple[FaceRef, ...], ...]


@dataclass(frozen=True)
class ScoreResponse:
    """The per-frame per-face SPEAKING score grid + the engine tag the worker logs."""

    scores: tuple[tuple[float, ...], ...]
    engine: str = ENGINE_LR_ASD

    def to_dict(self) -> dict:
        return {
            "engine": self.engine,
            "scores": [list(row) for row in self.scores],
        }
