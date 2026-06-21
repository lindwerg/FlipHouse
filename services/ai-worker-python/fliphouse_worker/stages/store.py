"""store stage — assemble result.json the Node ``publish`` finalizer consumes.

Reads the reframe manifest and emits, per clip, its R2 object key (derived from
the manifest input's prefix) plus the rank/score metadata the dashboard `clips`
rows need. Presign + DB writes stay in Node ``publish``; this is the bridge.
"""

from __future__ import annotations

import json
from time import perf_counter

from ._types import StageDeps
from .artifacts import content_key
from .workspace import download_inputs, job_workspace, upload_outputs

RESULT_SCHEMA_VERSION = 1


def _clip_prefix(manifest_key: str) -> str:
    """The R2 prefix the reframe clips live under (manifest's own parent)."""
    return manifest_key.rsplit("/", 1)[0] if "/" in manifest_key else ""


def _result_clip(prefix: str, entry: dict) -> dict:
    return {
        "rank": entry["rank"],
        "key": content_key(prefix, entry["path"]),
        "title": entry["title"],
        "score": entry["score"],
        "duration_s": entry["duration_s"],
        "width": entry["width"],
        "height": entry["height"],
    }


def store_handler(req: dict, deps: StageDeps) -> dict:
    """manifest.json → result.json (clip R2 keys + ranked metadata for publish)."""
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("manifest",))
        started = perf_counter()
        manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
        prefix = _clip_prefix(req["inputs"]["manifest"])
        clips = [_result_clip(prefix, entry) for entry in manifest["clips"]]

        result = {
            "schema_version": RESULT_SCHEMA_VERSION,
            "clip_count": len(clips),
            "clips": clips,
        }
        result_path = ws / "result.json"
        result_path.write_text(json.dumps(result, ensure_ascii=False), encoding="utf-8")

        refs = upload_outputs(deps.r2, req["outputPrefix"], [result_path])
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "clip_count": len(clips),
            },
        }
