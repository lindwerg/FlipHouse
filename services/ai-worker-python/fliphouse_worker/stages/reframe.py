"""reframe stage — render the ranked clips to 9:16 mp4s + manifest.json in R2.

Rebuilds ``SelectedClip`` objects from clips.json, runs the vertical renderer
into an isolated subdir (so the downloaded inputs never get re-uploaded), and
ships every ``clip_NN.mp4`` plus the manifest.
"""

from __future__ import annotations

import json
from time import perf_counter

from ..clipping.render import MANIFEST_NAME
from ._types import StageDeps
from .clips_io import load_selected_clips
from .workspace import download_inputs, job_workspace, upload_outputs


def reframe_handler(req: dict, deps: StageDeps) -> dict:
    """source(proxy) + clips.json → clip_00.mp4 … + manifest.json (uploaded)."""
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("source", "clips"))
        started = perf_counter()
        payload = json.loads(inputs["clips"].read_text(encoding="utf-8"))
        clips = load_selected_clips(payload)

        out_dir = ws / "render"
        out_dir.mkdir()
        manifest = deps.render(clips, str(inputs["source"]), out_dir)

        outputs = sorted(out_dir.glob("clip_*.mp4")) + [out_dir / MANIFEST_NAME]
        refs = upload_outputs(deps.r2, req["outputPrefix"], outputs)
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "clip_count": manifest.clip_count,
            },
        }
