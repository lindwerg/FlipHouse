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

``build_handlers`` (the dispatch registry) is added in the build-handlers step;
until then this package exposes only the pure helpers (``artifacts``).
"""
