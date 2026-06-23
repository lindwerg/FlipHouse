"""score stage — cascade the proxy + transcript into ranked clips.json in R2.

The clips.json the reframe stage consumes carries the full ranked cascade so the
expensive networked scoring runs exactly once.
"""

from __future__ import annotations

import json
from time import perf_counter

from ._types import StageDeps
from .clips_io import dump_clips
from .workspace import download_inputs, job_workspace, upload_outputs


def score_handler(req: dict, deps: StageDeps) -> dict:
    """source(proxy) + transcript(cascade) → clips.json (ranked, with cost)."""
    with job_workspace(req) as ws:
        inputs = download_inputs(
            deps.r2, req, ws, required=("source", "transcript", "word_segments")
        )
        started = perf_counter()
        transcript = json.loads(inputs["transcript"].read_text(encoding="utf-8"))
        # Per-word timings drive boundary snapping (refine_boundaries) inside the
        # cascade — injected into params so a clip never cuts mid-word. The asr
        # stage always emits word_segments.json, so a missing one is a loud wiring
        # bug (download_inputs raises), not a silent text-bounds fallback.
        word_segments = json.loads(inputs["word_segments"].read_text(encoding="utf-8"))
        params = {**req["params"], "word_segments": word_segments}
        result = deps.score_clips(transcript, str(inputs["source"]), params)

        payload = dump_clips(result)
        clips_path = ws / "clips.json"
        clips_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")

        refs = upload_outputs(deps.r2, req["outputPrefix"], [clips_path])
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "clip_count": len(result.clips),
                "cost_usd_micros": payload["cost_usd_micros"],
            },
        }
