"""asr-finalize stage — GigaAM-v3 GPU raw payload (webhook) → R2 transcript contracts.

The GPU GigaAM-v3 lane runs off-Railway and delivers its raw result via webhook;
the Node side parks that raw payload at ``rawPayloadKey`` in R2 and then invokes
``python -m fliphouse_worker.cli asr-finalize`` with the JSON contract:

    {"rawPayloadKey": "intermediate/<hash>/asr/_raw_gigaam.json",
     "outputPrefix":  "intermediate/<hash>/asr",
     "engine":        "gigaam-v3"}

This handler downloads that raw payload, VALIDATES it (fail-loud on drift via
``validate_gigaam_payload``), normalizes it through the SAME ``normalize_segments``
the inline ASR path uses, projects the single :class:`Transcript` onto the two
canonical contracts (``cascade_transcript.json`` + ``word_segments.json``), uploads
both, and writes the ``_COMPLETE`` sentinel LAST — so a crash between the two
uploads leaves no sentinel and the step re-runs cleanly. Idempotent: a present
sentinel short-circuits all work.
"""

from __future__ import annotations

import json
from time import perf_counter

from ..transcription import normalize_segments, validate_gigaam_payload
from ._types import StageDeps
from .artifacts import artifact_ref, content_key
from .workspace import job_workspace

# Written LAST under outputPrefix; its presence means the finalize is durable+complete.
COMPLETE_SENTINEL_NAME = "_COMPLETE"
DEFAULT_ENGINE = "gigaam-v3"


def asr_finalize_handler(req: dict, deps: StageDeps) -> dict:
    """raw GigaAM payload (R2) → validated → normalized → two contracts + sentinel."""
    raw_key = req.get("rawPayloadKey")
    if not raw_key:
        raise ValueError("asr-finalize request missing required 'rawPayloadKey'")
    output_prefix = req.get("outputPrefix")
    if not output_prefix:
        raise ValueError("asr-finalize request missing required 'outputPrefix'")

    sentinel_key = content_key(output_prefix, COMPLETE_SENTINEL_NAME)
    if deps.r2.object_exists(sentinel_key):
        # Already finalized — do not re-download or re-upload (idempotent skip).
        return {"outputs": [], "metrics": {"skipped": 1, "segment_count": 0}}

    engine = req.get("engine", DEFAULT_ENGINE)
    with job_workspace(req) as ws:
        started = perf_counter()
        raw_local = ws / "_raw_gigaam.json"
        deps.r2.download_file(raw_key, raw_local)
        payload = json.loads(raw_local.read_text(encoding="utf-8"))

        validated = validate_gigaam_payload(payload)
        transcript = normalize_segments(
            validated.segments,
            duration=validated.duration,
            language=validated.language,
            engine=engine,
        )

        word_segments = ws / "word_segments.json"
        cascade = ws / "cascade_transcript.json"
        word_segments.write_text(
            json.dumps(transcript.to_word_segments(), ensure_ascii=False), encoding="utf-8"
        )
        cascade.write_text(
            json.dumps(transcript.to_cascade_dict(), ensure_ascii=False), encoding="utf-8"
        )

        # Upload the two canonical contracts; emit their ArtifactRefs. The sentinel
        # is uploaded LAST and AFTER — a crash mid-way leaves no sentinel → re-run.
        refs = []
        for path in (word_segments, cascade):
            key = content_key(output_prefix, path.name)
            deps.r2.upload_file(path, key)
            refs.append(artifact_ref(key, path))

        sentinel = ws / COMPLETE_SENTINEL_NAME
        sentinel.write_text(engine, encoding="utf-8")
        deps.r2.upload_file(sentinel, sentinel_key)

        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "segment_count": len(transcript.segments),
                "skipped": 0,
            },
        }
