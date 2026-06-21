"""caption / banner passthrough — P2 no-op stages in the linear chain.

The real caption burn-in (P3) and offer banner (P4) replace these. Until then
they must EXIST as registered Python stages: an unregistered stage returns fatal
``UNKNOWN_STAGE`` and hard-fails the flow. Passthrough re-emits each input under
this stage's ``outputPrefix`` with its basename preserved, so the next stage
finds the artifacts where it expects them.
"""

from __future__ import annotations

from pathlib import Path
from time import perf_counter

from ._types import StageDeps
from .r2 import parse_key
from .workspace import job_workspace, upload_outputs


def passthrough_handler(req: dict, deps: StageDeps) -> dict:
    """Copy every input to ``outputPrefix/<same-basename>`` unchanged."""
    inputs = req.get("inputs", {})
    with job_workspace(req) as ws:
        started = perf_counter()
        out_paths: list[Path] = []
        for key in sorted(inputs.values()):
            local = ws / Path(parse_key(key)).name
            deps.r2.download_file(key, local)
            out_paths.append(local)
        refs = upload_outputs(deps.r2, req["outputPrefix"], out_paths)
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "passthrough": 1,
                "output_count": len(out_paths),
            },
        }
