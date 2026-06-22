"""transcode stage — normalize the source upload to a 720p proxy in R2.

The proxy is the single input every later CPU stage (asr/score/reframe) reads,
so a heavy 4K/HEVC upload is decoded once here instead of by each stage.
"""

from __future__ import annotations

from time import perf_counter

from ._types import StageDeps
from .workspace import download_inputs, job_workspace, upload_outputs


def transcode_handler(req: dict, deps: StageDeps) -> dict:
    """source → 720p H.264/AAC proxy.mp4 (uploaded). Empty output is fatal.

    Also probes the ORIGINAL source's duration and emits ``source_duration_ms`` —
    the PAYG billable quantity the Node side reads to charge the prepaid balance.
    """
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("source",))
        started = perf_counter()
        source_duration_ms = round(deps.probe_duration(inputs["source"]) * 1000)
        proxy = ws / "proxy.mp4"
        deps.transcode_ffmpeg(inputs["source"], proxy)
        if not proxy.exists() or proxy.stat().st_size == 0:
            raise ValueError("transcode produced no proxy output")
        refs = upload_outputs(deps.r2, req["outputPrefix"], [proxy])
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "source_duration_ms": source_duration_ms,
            },
        }
