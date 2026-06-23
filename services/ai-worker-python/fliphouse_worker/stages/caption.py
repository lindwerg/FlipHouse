"""caption stage — burn Russian word-highlight subtitles into the reframed clips.

Mirrors ``reframe.py``: download inputs (the reframe ``manifest.json`` + the ASR
``word_segments.json`` + each reframed ``clip_NN.mp4``), and for every clip slice
the words to its window, group them into lines, build a libass ``\\k`` karaoke
``.ass``, and burn it in with ONE LGPL-clean ffmpeg pass. Fail policy:

* fail-OPEN per clip — a clip with NO words in its window is copied through
  UNCHANGED (no captions is acceptable; a blocked clip is not), matching
  ``caption_band``'s fail-open contract.
* fail-CLOSED on a real burn — an empty output, a non-1080×1920 probe, or a burn
  exception RAISES (fatal), never a silently bad captioned clip.

Each captioned clip is written to a sibling ``*.partial``, verified, then
atomically promoted via the injected ``replace`` seam (same crash-safety as the
renderer). The updated manifest is written ATOMICALLY (tempfile → ``replace``),
then everything is uploaded under the caption ``outputPrefix``.
"""

from __future__ import annotations

import functools
import json
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter

from ..captioning.ass import build_caption_ass, group_caption_lines
from ..captioning.segments import slice_and_offset_words
from ..clipping.render import (
    MANIFEST_NAME,
    DimensionMismatchError,
    RenderOutputError,
)
from ..concurrency import MAX_CAPTION_WORKERS, MapFn, strict_ordered_threadpool_map
from ._types import StageDeps
from .workspace import download_inputs, job_workspace, upload_outputs

TARGET_W: int = 1080
TARGET_H: int = 1920
CLIPS_PREFIX_INPUT: str = "clips_prefix"

# Fail-closed bounded burn fan-out at the caption-specific cap.
_DEFAULT_CAPTION_MAP: MapFn = functools.partial(
    strict_ordered_threadpool_map, max_workers=MAX_CAPTION_WORKERS
)


@dataclass(frozen=True)
class CaptionResult:
    """One clip's caption outcome: ``burned`` is False on fail-open copy-through."""

    burned: bool


def caption_handler(req: dict, deps: StageDeps, *, _map_fn: MapFn = _DEFAULT_CAPTION_MAP) -> dict:
    """reframe manifest + word_segments + reframed clips → captioned clips + manifest.

    Each clip writes a distinct ``clip_NN.mp4`` (no shared mutation), so the burns
    run through a BOUNDED thread pool — wall-clock of the second encode drops ~Nx.
    The map is FAIL-CLOSED (``strict_ordered_threadpool_map``): an empty burn,
    wrong-dimension probe, or burn exception propagates and aborts the stage; it is
    never silently dropped. The manifest is written AFTER the map, so order and
    content are unchanged.
    """
    with job_workspace(req) as ws:
        inputs = download_inputs(deps.r2, req, ws, required=("manifest", "word_segments"))
        started = perf_counter()

        manifest = json.loads(inputs["manifest"].read_text(encoding="utf-8"))
        word_segments = json.loads(inputs["word_segments"].read_text(encoding="utf-8"))
        clips_prefix = req["inputs"][CLIPS_PREFIX_INPUT].rstrip("/")

        out_dir = ws / "caption"
        out_dir.mkdir()

        results = _map_fn(
            lambda clip: _caption_one_clip(deps, clip, word_segments, clips_prefix, out_dir),
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


def _caption_one_clip(
    deps: StageDeps,
    clip: dict,
    word_segments: object,
    clips_prefix: str,
    out_dir: Path,
) -> CaptionResult:
    """Caption (or copy through) one clip into ``out_dir``. ``burned`` iff captioned.

    Fail-open: no words in the clip window → the reframed clip is forwarded
    UNCHANGED. Fail-closed: a burn that yields an empty file or a wrong-dimension
    probe raises.
    """
    clip_name = clip["path"]
    src = out_dir / f"_src_{clip_name}"
    deps.r2.download_file(f"{clips_prefix}/{clip_name}", src)
    out_path = out_dir / clip_name

    words = slice_and_offset_words(
        word_segments, float(clip["start_time"]), float(clip["end_time"])
    )
    if not words:  # fail-open: pass the reframed clip through unchanged
        src.replace(out_path)
        return CaptionResult(burned=False)

    lines = group_caption_lines(words)
    ass_text = build_caption_ass(lines, source_caption_band=clip.get("caption_band"))

    out_partial = out_path.with_name(out_path.name + ".partial")
    deps.caption_burn(src, ass_text, out_partial)
    if not out_partial.exists() or out_partial.stat().st_size == 0:
        raise RenderOutputError(f"caption burn produced no output for {clip_name}")
    pw, ph = deps.probe(out_partial)
    if (pw, ph) != (TARGET_W, TARGET_H):
        raise DimensionMismatchError(
            f"captioned {clip_name} is {pw}x{ph}, expected {TARGET_W}x{TARGET_H}"
        )
    deps.replace(out_partial, out_path)
    src.unlink(missing_ok=True)
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
