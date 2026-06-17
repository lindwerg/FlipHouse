"""Vertical-render orchestrator (P2-2.4 render).

Consumes the cascade's ranked ``SelectedClip`` list + the source video and emits,
per clip, one **1080×1920 H.264/AAC mp4** (LGPL-clean ``libopenh264``, ``+faststart``)
plus a ``manifest.json``. Rank order is preserved end-to-end. Every impure boundary
(ffmpeg render, ffprobe, manifest write, wall clock) is an injectable seam so the
unit suite runs 100% offline. Fail-closed: a non-positive or >180 s span, an empty
output file, or a non-1080×1920 probe all raise — never a silent bad clip.

``SelectedClip`` is imported only under ``TYPE_CHECKING``: ``engine.cascade`` imports
``..clipping`` at runtime, so a runtime import here would be a cycle.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..video_asserts import probe_dimensions
from .crop_geometry import (
    BLURPAD_MODE,
    TARGET_H,
    TARGET_W,
    CropBox,
    clip_filename,
    compute_crop_box,
    round_duration,
)
from .manifest import ENGINE_NAME, MANIFEST_SCHEMA_VERSION, ClipEntry, RenderManifest
from .speaker_region import MediapipeSpeakerRegionSelector, SpeakerRegionSelector

if TYPE_CHECKING:  # cycle break: engine.cascade imports ..clipping at runtime
    from ..engine.cascade import SelectedClip

logger = logging.getLogger(__name__)

TARGET_BITRATE: str = "6M"
MAXRATE: str = "8M"  # > b:v so libopenh264 overshoots rather than dropping frames
BUFSIZE: str = "12M"
AUDIO_BITRATE: str = "128k"
GOP: int = 60
GBLUR_SIGMA: int = 20
MANIFEST_NAME: str = "manifest.json"
MAX_CLIP_DURATION_S: float = 180.0  # Shorts hard cap (doc 04 §3.2)

RenderFn = Callable[[str, float, float, "CropBox", Path, int, int, str], None]
ProbeFn = Callable[[Path], tuple[int, int]]
WriteFn = Callable[[Path, "dict[str, object]"], None]
ClockFn = Callable[[], str]


class DimensionMismatchError(RuntimeError):
    """Rendered clip is not exactly target_w × target_h (fail-closed)."""


class RenderOutputError(RuntimeError):
    """ffmpeg returned 0 but produced a missing/empty output file (fail-closed)."""


class ClipDurationError(RuntimeError):
    """A clip span exceeds MAX_CLIP_DURATION_S (fail-closed)."""


# ---- pure builders (unit-tested directly, no ffmpeg) ----


def _build_crop_filtergraph(box: CropBox, w: int, h: int) -> str:
    """Speaker-crop graph: crop the 9:16 column, scale to target, square pixels."""
    return f"crop={box.w}:{box.h}:{box.x}:{box.y},scale={w}:{h},setsar=1"


def _build_blurpad_filtergraph(w: int, h: int, sigma: int = GBLUR_SIGMA) -> str:
    """Blur-pad graph: a blurred cover-fill background behind the letterboxed foreground.

    The foreground uses ``force_original_aspect_ratio=decrease`` (fit, never crop) so
    a tall source is letterboxed against the blur instead of head-cropped.
    """
    return (
        f"split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={sigma}[bgb];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fgs];"
        f"[bgb][fgs]overlay=(W-w)/2:(H-h)/2,setsar=1"
    )


def _build_render_argv(
    src: str,
    start: float,
    end: float,
    box: CropBox,
    out: Path,
    w: int,
    h: int,
    bitrate: str,
) -> list[str]:
    """Build the full LGPL-clean ffmpeg argv. libopenh264 has NO ``-crf`` — use ABR.

    ``-ss`` before ``-i`` (fast accurate re-encode seek, mirrors cutter). ABR via
    ``-b:v``/``-maxrate``/``-bufsize`` (NOT ``-crf``, NOT the build-specific
    ``-rc_mode``). ``-maxrate`` > ``-b:v`` lets libopenh264 overshoot rather than
    drop frames; the build-specific ``-allow_skip_frames`` knob is NOT portable
    across ffmpeg builds (verified absent on a real install) so it is omitted.
    Output is a real seekable file (``+faststart`` needs one).
    """
    graph = (
        _build_blurpad_filtergraph(w, h)
        if box.mode == BLURPAD_MODE
        else _build_crop_filtergraph(box, w, h)
    )
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-ss",
        f"{start}",
        "-i",
        src,
        "-t",
        f"{end - start}",
        "-vf",
        graph,
        "-c:v",
        "libopenh264",
        "-profile",
        "high",
        "-b:v",
        bitrate,
        "-maxrate",
        MAXRATE,
        "-bufsize",
        BUFSIZE,
        "-g",
        str(GOP),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        str(out),
    ]


# ---- impure seams ----


def _run_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one delivery clip (the only ffmpeg call). Argv is built/tested purely."""
    subprocess.run(_build_render_argv(src, start, end, box, out, w, h, bitrate), check=True)


def _write_manifest_json(path: Path, data: dict[str, object]) -> None:
    """Write the manifest dict as pretty UTF-8 JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:  # pragma: no cover - wall clock, injected in tests
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _resolve_box(traj_general: bool, src_w: int, src_h: int, center: float | None) -> CropBox:
    """Pick the crop window: blur-pad on a GENERAL trajectory, else the speaker column."""
    if traj_general:
        return CropBox(x=0, y=0, w=src_w, h=src_h, mode=BLURPAD_MODE)
    return compute_crop_box(src_w, src_h, center)


def render_vertical_clips(
    clips: Sequence[SelectedClip],
    src_path: str,
    out_dir: str | Path,
    scene_cut_times: Sequence[float] = (),
    *,
    target_w: int = TARGET_W,
    target_h: int = TARGET_H,
    engine: str = ENGINE_NAME,
    bitrate: str = TARGET_BITRATE,
    selector: SpeakerRegionSelector | None = None,
    _render_fn: RenderFn = _run_render_ffmpeg,
    _probe_fn: ProbeFn = probe_dimensions,
    _write_fn: WriteFn = _write_manifest_json,
    _clock: ClockFn = _utc_now_iso,
) -> RenderManifest:
    """Render the ranked cascade clips to vertical mp4s + ``manifest.json``.

    Rank-preserving (sorts by ``SelectedClip.rank`` defensively, re-derives
    ``ClipEntry.rank=i``). ``scene_cut_times`` are the PRECOMPUTED whole-video cuts
    (``LocalSignals.scene_cuts``); the selector windows/offsets them per clip — no
    re-detection. Fail-closed on bad span / >180 s / empty output / probe mismatch.
    Empty clips → a valid manifest with ``clip_count=0`` and no ffmpeg call.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    selector = selector or MediapipeSpeakerRegionSelector()

    ordered = sorted(clips, key=lambda c: c.rank)
    if [c.rank for c in ordered] != list(range(len(ordered))):
        raise RuntimeError(
            f"clip ranks are not a contiguous 0..n-1 set: {[c.rank for c in ordered]}"
        )

    entries: list[ClipEntry] = []
    for i, clip in enumerate(ordered):
        start = clip.candidate.start_time
        end = clip.candidate.end_time
        span = end - start
        if span <= 0:
            raise ValueError(f"clip span must be positive, got [{start}, {end}]")
        if span > MAX_CLIP_DURATION_S:
            raise ClipDurationError(f"clip span {span}s exceeds cap {MAX_CLIP_DURATION_S}s")

        traj = selector.select_speaker_region(src_path, start, end, scene_cut_times)
        is_general = traj.is_general()
        center = None if is_general else traj.dominant_center()
        box = _resolve_box(is_general, traj.source_width, traj.source_height, center)

        out_path = out_dir / clip_filename(i)
        _render_fn(src_path, start, end, box, out_path, target_w, target_h, bitrate)
        if not out_path.exists() or out_path.stat().st_size == 0:
            raise RenderOutputError(f"ffmpeg produced no output at {out_path}")
        rw, rh = _probe_fn(out_path)
        if (rw, rh) != (target_w, target_h):
            raise DimensionMismatchError(f"clip {i} is {rw}x{rh}, expected {target_w}x{target_h}")

        entries.append(
            ClipEntry(
                rank=i,
                score=clip.scored.aggregate,
                sub_scores=clip.scored.sub_scores,
                confidence=clip.scored.confidence,
                start_time=start,
                end_time=end,
                duration_s=round_duration(start, end),
                width=target_w,
                height=target_h,
                path=clip_filename(i),
                title=clip.candidate.title,
                used_video=clip.used_video,
                model_used=clip.scored.model_used,
                modalities_used=clip.scored.modalities_used,
            )
        )

    manifest = RenderManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source=os.path.basename(src_path),
        engine=engine,
        generated_at=_clock(),
        resolution=[target_w, target_h],
        clip_count=len(entries),
        clips=tuple(entries),
    )
    _write_fn(out_dir / MANIFEST_NAME, manifest.to_dict())
    return manifest
