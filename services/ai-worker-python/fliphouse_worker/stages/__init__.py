"""R2/ffmpeg-backed worker stage handlers (P2 step 2.5).

The Node BullMQ worker drives each pipeline stage via ``python -m
fliphouse_worker.cli <stage>``. ``cli/_dispatch.py`` is the pure transport +
classifier; THIS package is the impure body: each handler fetches its inputs
from R2, runs the existing compute core (transcode / asr / score / reframe /
store), uploads its outputs to R2, and returns ``{outputs, metrics}``.

Idempotency is owned by the Node side (the ``execute-stage.ts`` sentinel +
``upload_ledger``); Python stays stateless compute. It only guarantees the three
properties that make that authority crash-safe: deterministic content-addressed
output keys, crash-safe local artifact materialization (``.partial`` →
``os.replace``), and a streamed SHA-256 on every uploaded artifact.

``build_handlers`` is re-exported lazily so importing a pure helper
(``fliphouse_worker.stages.artifacts``) never pulls in boto3 / the renderer.
"""

from __future__ import annotations

__all__ = ["build_handlers"]


def build_handlers(deps: object | None = None) -> dict:
    """Return the ``{stage: handler}`` registry the CLI dispatches over (lazy import)."""
    from ._registry import build_handlers as _build

    return _build(deps)
