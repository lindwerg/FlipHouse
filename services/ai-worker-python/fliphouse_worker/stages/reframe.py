"""reframe stage — render the ranked clips to 9:16 mp4s + manifest.json in R2.

Rebuilds ``SelectedClip`` objects from clips.json, runs the vertical renderer
into an isolated subdir (so the downloaded inputs never get re-uploaded), and
ships every ``clip_NN.mp4`` plus the manifest.

SPD-1: the per-word caption ``.ass`` is built here and folded into the SAME
libopenh264 reframe encode, so each delivery clip is encoded ONCE (the separate
caption-burn re-encode is retired). ``word_segments`` is a FAIL-OPEN input — when
it is missing or empty the renderer falls back to uncaptioned clips exactly as
before, and the downstream caption stage simply forwards the clips unchanged.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from time import perf_counter

from ..captioning.ass import build_caption_ass, group_caption_lines
from ..captioning.segments import slice_and_offset_words
from ..clipping.render import MANIFEST_NAME
from ._types import StageDeps
from .clips_io import load_scene_cut_times, load_selected_clips
from .workspace import download_inputs, job_workspace, upload_outputs


def build_caption_ass_fn(
    word_segments: object,
) -> Callable[[float, float, dict[str, object] | None], str | None]:
    """A per-clip ``CaptionAssFn`` over ``word_segments`` (PURE; injected into the renderer).

    For each clip window it slices the words to the window, groups them into lines, and
    builds the libass per-word reveal ``.ass`` — the EXACT same construction the retired
    caption stage performed, so the burned pixels are byte-identical; only the encode is
    now shared with the reframe pass. Fail-OPEN: a clip with no in-window words returns
    None → an uncaptioned clip (never blocks a paid render), matching the old fail-open.
    """

    def _ass_for(start: float, end: float, band: dict[str, object] | None) -> str | None:
        words = slice_and_offset_words(word_segments, start, end)
        if not words:
            return None
        lines = group_caption_lines(words)
        return build_caption_ass(lines, source_caption_band=band)

    return _ass_for


def reframe_handler(req: dict, deps: StageDeps) -> dict:
    """source(proxy) + clips.json (+ word_segments) → captioned clip_00.mp4 … + manifest."""
    with job_workspace(req) as ws:
        # word_segments is FAIL-OPEN: present in the live wiring (asr emits it), but a v1
        # request without it just yields uncaptioned clips rather than failing the stage.
        inputs = download_inputs(
            deps.r2, req, ws, required=("source", "clips"), optional=("word_segments",)
        )
        started = perf_counter()
        payload = json.loads(inputs["clips"].read_text(encoding="utf-8"))
        clips = load_selected_clips(payload)
        # Scene cuts (source-absolute) drive the One-Euro reset + segment cut-snap in
        # the renderer; a v1 clips.json without them loads as () (no-snap, no crash).
        scene_cut_times = load_scene_cut_times(payload)

        ws_path = inputs.get("word_segments")
        word_segments = json.loads(ws_path.read_text(encoding="utf-8")) if ws_path else ()
        caption_ass_fn = build_caption_ass_fn(word_segments)

        out_dir = ws / "render"
        out_dir.mkdir()
        manifest = deps.render(
            clips,
            str(inputs["source"]),
            out_dir,
            scene_cut_times,
            _caption_ass_fn=caption_ass_fn,
        )

        outputs = sorted(out_dir.glob("clip_*.mp4")) + [out_dir / MANIFEST_NAME]
        refs = upload_outputs(deps.r2, req["outputPrefix"], outputs)
        return {
            "outputs": refs,
            "metrics": {
                "duration_ms": round((perf_counter() - started) * 1000),
                "clip_count": manifest.clip_count,
            },
        }
