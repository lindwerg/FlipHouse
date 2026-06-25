"""caption stage — forward the already-captioned reframe clips (no re-encode).

SPD-1 retired the second libopenh264 caption-burn pass: the per-word Russian
highlight ``.ass`` is now burned into the SAME reframe encode (see
``stages/reframe.build_caption_ass_fn``), so each delivery clip is encoded ONCE.
This stage therefore only FORWARDS the reframe outputs (the ``manifest.json`` +
each ``clip_NN.mp4``) under the caption ``outputPrefix`` so the publish finalizer's
existing prefix wiring is untouched — no ffmpeg runs here at all.

Fail policy: fail-CLOSED on a missing clip the manifest names (a forward that loses
a paid clip is fatal). The manifest is forwarded byte-identical (clip windows +
``caption_band`` already drove the burn upstream).
"""

from __future__ import annotations

import functools
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from ..clipping.render import MANIFEST_NAME, RenderOutputError
from ..concurrency import MAX_CAPTION_WORKERS, MapFn, strict_ordered_threadpool_map
from ._types import StageDeps
from .workspace import download_inputs, job_workspace, upload_outputs

TARGET_W: int = 1080
TARGET_H: int = 1920
CLIPS_PREFIX_INPUT: str = "clips_prefix"

# Fail-closed bounded forward fan-out at the caption-specific cap (downloads only).
_DEFAULT_CAPTION_MAP: MapFn = functools.partial(
    strict_ordered_threadpool_map, max_workers=MAX_CAPTION_WORKERS
)


@dataclass(frozen=True)
class CaptionResult:
    """One clip's forward outcome (``burned`` kept for the metric's stable shape).

    SPD-1: the burn happened upstream in the reframe encode, so a forwarded clip is
    already captioned. ``burned`` stays True here so the ``captioned`` metric continues
    to count delivered clips (the publish/UI contract is unchanged)."""

    burned: bool


def caption_handler(req: dict, deps: StageDeps, *, _map_fn: MapFn = _DEFAULT_CAPTION_MAP) -> dict:
    """reframe manifest + already-captioned reframe clips → forwarded clips + manifest.

    No re-encode (SPD-1): each ``clip_NN.mp4`` is downloaded from the reframe prefix and
    re-uploaded under the caption ``outputPrefix`` unchanged. Downloads run through a
    BOUNDED thread pool; the map is FAIL-CLOSED — a clip the manifest names but R2 can't
    supply raises and aborts the stage rather than silently dropping a paid clip.
    """
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("manifest",))
        started = perf_counter()

        manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
        clips_prefix = req["inputs"][CLIPS_PREFIX_INPUT].rstrip("/")

        out_dir = ws / "caption"
        out_dir.mkdir()

        results = _map_fn(
            lambda clip: _forward_one_clip(deps, clip, clips_prefix, out_dir),
            manifest.get("clips", []),
        )
        captioned = sum(1 for r in results if r.burned)

        _write_manifest_atomic(deps, manifest, out_dir / MANIFEST_NAME)

        outputs = sorted(out_dir.glob("clip_*.mp4")) + [out_dir / MANIFEST_NAME]
        refs = upload_outputs(deps.r2, req["outputPrefix"], outputs)
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "clip_count": len(manifest.get("clips", [])),
                "captioned": captioned,
            },
        }


def _forward_one_clip(
    deps: StageDeps,
    clip: dict,
    clips_prefix: str,
    out_dir: Path,
) -> CaptionResult:
    """Forward one already-captioned reframe clip into ``out_dir`` (no re-encode).

    Fail-closed: the manifest named the clip, so an empty/absent download is fatal —
    a forward that loses a paid clip must abort the stage, never silently continue.
    """
    clip_name = clip["path"]
    out_path = out_dir / clip_name
    deps.r2.download_file(f"{clips_prefix}/{clip_name}", out_path)
    if not out_path.exists() or out_path.stat().st_size == 0:
        raise RenderOutputError(f"caption forward produced no output for {clip_name}")
    return CaptionResult(burned=True)


def _write_manifest_atomic(deps: StageDeps, manifest: dict, path: Path) -> None:
    """Write the (possibly mutated) manifest as pretty UTF-8 JSON, atomically.

    A tempfile in the SAME dir (→ same filesystem) is written then promoted via
    the injected ``replace`` seam, so a crash never leaves a half-written
    manifest a downstream reader could parse-fail on.
    """
    fd, tmp_name = tempfile.mkstemp(
        suffix=".json", prefix="fh_caption_manifest_", dir=str(path.parent)
    )
    tmp_path = Path(tmp_name)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(json.dumps(manifest, ensure_ascii=False, indent=2))
    deps.replace(tmp_path, path)
