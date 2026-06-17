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
import shutil
import subprocess
import tempfile
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
    round_duration,
)
from .manifest import ENGINE_NAME, MANIFEST_SCHEMA_VERSION, ClipEntry, RenderManifest
from .segments import RenderSegment, build_render_segments
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
# Video-only segment render (no audio) — same shape as RenderFn but the argv adds -an.
VideoRenderFn = Callable[[str, float, float, "CropBox", Path, int, int, str], None]
# Concatenate video parts + a SINGLE per-clip audio cut → one muxed mp4.
ConcatMuxFn = Callable[[Sequence[Path], str, float, float, Path], None]
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


def _build_video_render_argv(
    src: str,
    start: float,
    end: float,
    box: CropBox,
    out: Path,
    w: int,
    h: int,
    bitrate: str,
) -> list[str]:
    """VIDEO-ONLY segment render (``-an``): one reframe segment of a multi-segment clip.

    Audio is deliberately omitted — it is cut exactly ONCE per clip in the concat
    step, never per segment, so accumulating AAC priming can't drift A/V out of
    sync across the joins (the very defect this feature removes).
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
        "-an",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _build_concat_list(parts: Sequence[Path]) -> str:
    """concat-demuxer list text: one ``file '<abs>'`` line per part (apostrophes escaped)."""
    apostrophe = "'"
    escaped_apostrophe = "'\\''"  # concat-demuxer convention: close, literal ', reopen
    lines = [
        f"file '{str(Path(p).resolve()).replace(apostrophe, escaped_apostrophe)}'" for p in parts
    ]
    return "\n".join(lines) + "\n"


def _build_concat_mux_argv(
    list_path: Path, src: str, start: float, end: float, out: Path
) -> list[str]:
    """Concat the video parts (``-c:v copy``) + ONE clip-wide audio cut from ``src``.

    Input 0 is the concat-demuxer video; input 1 is the source seeked to the clip
    window (``-ss start`` … ``-t span``). ``-shortest`` + the single audio cut keep
    lips locked to sound regardless of how many video segments were joined.
    """
    span = end - start
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-f",
        "concat",
        "-safe",
        "0",
        "-i",
        str(list_path),
        "-ss",
        f"{start}",
        "-i",
        src,
        "-t",
        f"{span}",
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        AUDIO_BITRATE,
        "-ar",
        "48000",
        "-ac",
        "2",
        "-shortest",
        "-movflags",
        "+faststart",
        str(out),
    ]


def _write_concat_list(text: str) -> Path:
    """Write a concat-demuxer list to a temp file and return its path (covered helper)."""
    fd, name = tempfile.mkstemp(suffix=".txt", prefix="fh_concat_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return Path(name)


# ---- impure seams ----


def _run_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one delivery clip (the only ffmpeg call). Argv is built/tested purely."""
    subprocess.run(_build_render_argv(src, start, end, box, out, w, h, bitrate), check=True)


def _run_video_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one VIDEO-ONLY reframe segment. Argv is built/tested purely."""
    subprocess.run(_build_video_render_argv(src, start, end, box, out, w, h, bitrate), check=True)


def _run_concat_mux_ffmpeg(
    parts: Sequence[Path], src: str, start: float, end: float, out: Path
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Concat video parts + one audio cut → final mp4. List build/argv tested purely."""
    list_path = _write_concat_list(_build_concat_list(parts))
    try:
        subprocess.run(_build_concat_mux_argv(list_path, src, start, end, out), check=True)
    finally:
        list_path.unlink(missing_ok=True)


def _write_manifest_json(path: Path, data: dict[str, object]) -> None:
    """Write the manifest dict as pretty UTF-8 JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:  # pragma: no cover - wall clock, injected in tests
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _render_segments(
    src_path: str,
    start: float,
    out_path: Path,
    segments: Sequence[RenderSegment],
    *,
    target_w: int,
    target_h: int,
    bitrate: str,
    rank: int,
    _video_render_fn: VideoRenderFn,
    _concat_mux_fn: ConcatMuxFn,
    _probe_fn: ProbeFn,
) -> None:
    """Render each reframe segment VIDEO-ONLY (fail-closed per part), then concat +
    one clip-wide audio cut. Segment temp dir lives OUTSIDE out_dir and is swept."""
    end = start + segments[-1].end_s
    seg_dir = Path(tempfile.mkdtemp(prefix=f"fh_seg_{rank:02d}_"))
    try:
        parts: list[Path] = []
        for j, seg in enumerate(segments):
            part = seg_dir / f"part_{j:02d}.mp4"
            _video_render_fn(
                src_path,
                start + seg.start_s,
                start + seg.end_s,
                seg.box,
                part,
                target_w,
                target_h,
                bitrate,
            )
            if not part.exists() or part.stat().st_size == 0:
                raise RenderOutputError(f"clip {rank} segment {j} produced no output")
            pw, ph = _probe_fn(part)
            if (pw, ph) != (target_w, target_h):
                raise DimensionMismatchError(
                    f"clip {rank} segment {j} is {pw}x{ph}, expected {target_w}x{target_h}"
                )
            parts.append(part)
        _concat_mux_fn(parts, src_path, start, end, out_path)
    finally:
        shutil.rmtree(seg_dir, ignore_errors=True)


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
    _video_render_fn: VideoRenderFn = _run_video_render_ffmpeg,
    _concat_mux_fn: ConcatMuxFn = _run_concat_mux_ffmpeg,
    _probe_fn: ProbeFn = probe_dimensions,
    _write_fn: WriteFn = _write_manifest_json,
    _clock: ClockFn = _utc_now_iso,
) -> RenderManifest:
    """Render the ranked cascade clips to vertical mp4s + ``manifest.json``.

    Each clip's trajectory is split into CROP/BLURPAD render segments (dynamic
    reframe): a single-segment clip takes the fast path (one ``_render_fn`` with
    audio); a multi-segment clip renders each segment VIDEO-ONLY then concatenates
    them with ONE clip-wide audio cut (no per-segment A/V drift). Rank-preserving;
    ``scene_cut_times`` are the PRECOMPUTED whole-video cuts. Fail-closed on bad
    span / >180 s / empty (per-segment AND final) output / probe mismatch. Empty
    clips → a valid manifest with ``clip_count=0`` and no ffmpeg call.
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
        cuts_rel = [c - start for c in scene_cut_times if start <= c < end]
        segments = build_render_segments(traj, clip_duration=span, scene_cut_times=cuts_rel)

        out_path = out_dir / clip_filename(i)
        if len(segments) == 1:  # fast path — one render with audio (back-compat)
            _render_fn(src_path, start, end, segments[0].box, out_path, target_w, target_h, bitrate)
        else:
            _render_segments(
                src_path,
                start,
                out_path,
                segments,
                target_w=target_w,
                target_h=target_h,
                bitrate=bitrate,
                rank=i,
                _video_render_fn=_video_render_fn,
                _concat_mux_fn=_concat_mux_fn,
                _probe_fn=_probe_fn,
            )
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
                segment_count=len(segments),
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
