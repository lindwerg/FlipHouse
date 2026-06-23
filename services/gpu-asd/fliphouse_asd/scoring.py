"""Orchestration of one ``/score`` request — the LR-ASD model call injected.

The heavy work (fetch the proxy window, S3FD face-detect + track, run LR-ASD,
project per-track scores back onto the worker's per-frame face boxes) lives behind
ONE injected ``ScoreFn`` boundary so this orchestration is 100% unit-covered with a
fake. :func:`run_scoring` validates the returned grid's SHAPE against the request
(one score per face per frame) and clamps every score to ``[0, 1]`` — a model that
returns a mis-shaped grid is a :class:`ScoringError`, never a silent wrong answer the
worker would zip onto the wrong face.
"""

from __future__ import annotations

from collections.abc import Callable

from .contracts import ScoreRequest, ScoreResponse
from .errors import ScoringError

# score_fn(req) -> per-frame per-face raw speaking scores (same ragged shape as
# ``req.frames``). The live impl runs S3FD + LR-ASD on the GPU; tests inject a fake.
ScoreFn = Callable[[ScoreRequest], tuple[tuple[float, ...], ...]]


def _clamp_unit(value: float) -> float:
    """Clamp a raw model score into ``[0, 1]`` (LR-ASD logits are sigmoid-ish but noisy)."""
    return min(1.0, max(0.0, float(value)))


def _shape_matches(req: ScoreRequest, scores: tuple[tuple[float, ...], ...]) -> bool:
    """True when ``scores`` has exactly one value per face per frame of ``req``."""
    if len(scores) != len(req.frames):
        return False
    return all(len(row) == len(frame) for row, frame in zip(scores, req.frames, strict=True))


def run_scoring(req: ScoreRequest, score_fn: ScoreFn) -> ScoreResponse:
    """Run the model seam, validate the grid shape, and clamp → :class:`ScoreResponse`.

    Raises :class:`ScoringError` if the model raises or returns a grid that does not
    mirror the request's frame/face counts — the worker fails OPEN to its CPU heuristic
    on a non-2xx, so a clean error here is safer than a plausible-but-wrong grid.
    """
    try:
        raw = score_fn(req)
    except Exception as exc:  # noqa: BLE001 - any model fault becomes a typed ScoringError
        raise ScoringError(f"LR-ASD scoring failed: {exc}") from exc
    if not _shape_matches(req, raw):
        raise ScoringError("LR-ASD returned a score grid that does not match the request frames")
    clamped = tuple(tuple(_clamp_unit(s) for s in row) for row in raw)
    return ScoreResponse(scores=clamped)
