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
from collections.abc import Callable, Sequence
from functools import lru_cache
from time import perf_counter

from ..captioning.ass import (
    CAPTION_PRESETS,
    DEFAULT_PRESET,
    build_caption_ass,
    group_caption_lines,
)
from ..captioning.coverage import caption_coverage
from ..captioning.emoji import ALLOWED_EMOJI_CODEPOINTS, apply_line_emoji
from ..captioning.keywords import KeywordIndexSelector, apply_line_keywords
from ..captioning.preset import CaptionPreset
from ..captioning.segments import slice_and_offset_words
from ..clipping.render import MANIFEST_NAME
from ..engine.cascade import SelectedClip
from ._types import StageDeps
from .clips_io import load_scene_cut_times, load_selected_clips
from .workspace import download_inputs, job_workspace, upload_outputs

# A speech-scored clip whose captions cover less than this fraction of its wall-time is
# flagged as a silent caption dropout (the absolute-vs-relative ASR off-by-one). Telemetry
# only — the clip already shipped; this never blocks a render.
CAPTION_COVERAGE_EPSILON: float = 0.05


@lru_cache(maxsize=1)
def _runtime_emoji_capable() -> bool:  # pragma: no cover - infra probe, faked in tests
    """TRUE only if BOTH the build-set ``FH_EMOJI_CAPABLE`` flag AND the vendored colour-emoji
    font actually covers the EXACT allowlist (the env flag alone is not trusted).

    One-time, cached → zero per-request cost; reads the package-data ``NotoColorEmoji.ttf`` cmap
    (no network/subprocess). Any error → False (fail-OPEN, never a tofu box). The font + the
    build colour-smoke guard are added to the worker image in the activation step; until then
    the flag is unset → this returns False → emoji stays OFF.
    """
    import os

    if os.environ.get("FH_EMOJI_CAPABLE") != "1":
        return False
    try:
        from pathlib import Path

        from fontTools.ttLib import TTFont

        path = Path(__file__).resolve().parents[1] / "captioning" / "fonts" / "NotoColorEmoji.ttf"
        cmap = set(TTFont(path).getBestCmap())
        return ALLOWED_EMOJI_CODEPOINTS <= cmap
    except Exception:  # noqa: BLE001 — fail-open: any probe error → no emoji, never a crash
        return False


def build_caption_ass_fn(
    word_segments: object,
    *,
    preset: CaptionPreset = DEFAULT_PRESET,
    keyword_selector: KeywordIndexSelector | None = None,
    emoji_capable_fn: Callable[[], bool] = lambda: False,
) -> Callable[[float, float, dict[str, object] | None], str | None]:
    """A per-clip ``CaptionAssFn`` over ``word_segments`` (PURE; injected into the renderer).

    For each clip window it slices the words to the window, groups them into lines, and
    builds the libass per-word reveal ``.ass`` under ``preset`` (the job-selected caption
    look; ``DEFAULT_PRESET`` renders byte-identical to the retired caption stage, so live
    clips never regress — only the encode is now shared with the reframe pass). Fail-OPEN:
    a clip with no in-window words returns None → an uncaptioned clip (never blocks a paid
    render), matching the old fail-open.

    P3-A4: when the preset carries a ``keyword_colour`` AND a ``keyword_selector`` is injected,
    the grouped lines are stamped with at most one keyword word per line (strictly AFTER
    grouping). The selection runs in a dedicated try/except — ``_ass_for`` is invoked OUTSIDE
    render.py's encode try/except, so a raising keyword layer must degrade to the plain grouped
    caption, never fail the paid clip. The DEFAULT look (no ``keyword_colour``) skips it
    entirely → byte-identical.
    """

    def _ass_for(start: float, end: float, band: dict[str, object] | None) -> str | None:
        words = slice_and_offset_words(word_segments, start, end)
        if not words:
            return None
        lines = group_caption_lines(words)
        if preset.keyword_colour is not None and keyword_selector is not None:
            try:
                lines = apply_line_keywords(lines, keyword_selector)
            except Exception:  # noqa: BLE001 — fail-open: keep the plain grouped caption
                pass
        if preset.emoji_every_n:
            try:  # WHOLE emoji block fail-OPEN: any probe/stamp raise → plain caption
                if emoji_capable_fn():
                    lines = apply_line_emoji(
                        lines, emoji_capable=True, density_n=preset.emoji_every_n
                    )
            except Exception:  # noqa: BLE001 — never block a paid clip on emoji
                pass
        return build_caption_ass(lines, source_caption_band=band, preset=preset)

    return _ass_for


def _select_caption_preset(req: dict) -> CaptionPreset:
    """Resolve the job-selected caption look from the request (P3-A6).

    Fail-OPEN: an unknown/missing/non-string ``captionPreset`` falls back to
    ``DEFAULT_PRESET`` — a bad config string never blocks a paid render, it just renders
    the baseline look. The lookup is restricted to the curated :data:`CAPTION_PRESETS`
    registry, so only construction-valid presets can ever reach the renderer.
    """
    name = req.get("captionPreset")
    if not isinstance(name, str):
        return DEFAULT_PRESET
    return CAPTION_PRESETS.get(name, DEFAULT_PRESET)


def caption_coverage_metrics(
    clips: Sequence[SelectedClip], word_segments: object
) -> list[dict[str, object]]:
    """Per-clip caption-coverage telemetry (P3-C4) — READ-ONLY, never blocks a render.

    For each shipped clip, measure the fraction of its wall-window that carries captions
    (over the SAME ``word_segments`` and source-absolute window the renderer sliced) and
    flag a ``caption_dropout`` when a SPEECH-scored clip (non-empty transcript excerpt)
    rendered below :data:`CAPTION_COVERAGE_EPSILON` — the silent absolute-vs-relative ASR
    off-by-one. Pure observation folded into ``metrics`` after the clips already shipped.
    """
    metrics: list[dict[str, object]] = []
    for clip in clips:
        window = (clip.candidate.start_time, clip.candidate.end_time)
        coverage = caption_coverage(word_segments, window)
        speech_scored = bool(str(clip.candidate.text_excerpt).strip())
        metrics.append(
            {
                "rank": clip.rank,
                "caption_coverage": coverage,
                "speech_scored": speech_scored,
                "caption_dropout": speech_scored and coverage < CAPTION_COVERAGE_EPSILON,
            }
        )
    return metrics


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
        caption_ass_fn = build_caption_ass_fn(
            word_segments,
            preset=_select_caption_preset(req),
            keyword_selector=deps.keyword_selector,
            emoji_capable_fn=_runtime_emoji_capable,
        )

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
                "captions": caption_coverage_metrics(clips, word_segments),
            },
        }
