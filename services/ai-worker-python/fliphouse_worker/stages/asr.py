"""asr stage — proxy → 16 kHz mono wav → transcript → two JSON contracts in R2.

Emits both deliberately-separate transcript shapes (see transcription/provider.py):
``cascade_transcript.json`` (hard-subscript dict the scorer reads) and
``word_segments.json`` (per-word timings the P3 caption burn-in will read).
"""

from __future__ import annotations

import json
from time import perf_counter

from ._types import StageDeps
from .workspace import download_inputs, job_workspace, upload_outputs


def asr_handler(req: dict, deps: StageDeps) -> dict:
    """source(proxy) → word_segments.json + cascade_transcript.json (uploaded)."""
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("source",))
        started = perf_counter()
        wav = ws / "audio.wav"
        deps.extract_audio(inputs["source"], wav)
        transcript = deps.transcribe(wav, req["params"])

        word_segments = ws / "word_segments.json"
        cascade = ws / "cascade_transcript.json"
        word_segments.write_text(
            json.dumps(transcript.to_word_segments(), ensure_ascii=False), encoding="utf-8"
        )
        cascade.write_text(
            json.dumps(transcript.to_cascade_dict(), ensure_ascii=False), encoding="utf-8"
        )

        refs = upload_outputs(deps.r2, req["outputPrefix"], [word_segments, cascade])
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "segment_count": len(transcript.segments),
            },
        }
