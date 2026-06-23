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
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

from ..concurrency import MapFn, strict_ordered_threadpool_map
from ..video_asserts import probe_dimensions
from .caption_band import CaptionBandFn
from .crop_geometry import (
    BLURPAD_MODE,
    CONTAIN_LAYOUT,
    STACK_LAYOUT,
    TARGET_H,
    TARGET_W,
    CropBox,
    clip_filename,
    round_duration,
)
from .manifest import ENGINE_NAME, MANIFEST_SCHEMA_VERSION, ClipEntry, RenderManifest
from .segments import RenderSegment, build_render_segments
from .speaker_region import SpeakerRegionSelector, build_speaker_region_selector

if TYPE_CHECKING:  # cycle break: engine.cascade imports ..clipping at runtime
    from ..engine.cascade import SelectedClip

logger = logging.getLogger(__name__)

TARGET_BITRATE: str = "6M"
MAXRATE: str = "8M"  # > b:v so libopenh264 overshoots rather than dropping frames
BUFSIZE: str = "12M"
AUDIO_BITRATE: str = "128k"
GOP: int = 60
MANIFEST_NAME: str = "manifest.json"
MAX_CLIP_DURATION_S: float = 180.0  # Shorts hard cap (doc 04 §3.2)
MIN_RENDER_TIMEOUT_S: float = 30.0  # floor so a tiny clip's ffmpeg still gets headroom
RENDER_REALTIME_FACTOR: float = 4.0  # kill a hung ffmpeg at 4× the clip's real-time span

RenderFn = Callable[[str, float, float, "CropBox", Path, int, int, str], None]
# Video-only segment render (no audio) — same shape as RenderFn but the argv adds -an.
VideoRenderFn = Callable[[str, float, float, "CropBox", Path, int, int, str], None]
# Concatenate video parts + a SINGLE per-clip audio cut → one muxed mp4.
ConcatMuxFn = Callable[[Sequence[Path], str, float, float, Path], None]
ProbeFn = Callable[[Path], tuple[int, int]]
WriteFn = Callable[[Path, "dict[str, object]"], None]
ClockFn = Callable[[], str]
# Atomically promote a verified ``*.partial`` to its canonical path (default os.replace).
ReplaceFn = Callable[[Path, Path], None]


def _timeout_for(span_s: float) -> float:
    """ffmpeg timeout for a clip of ``span_s`` seconds: ``REALTIME_FACTOR``× real time,
    floored at ``MIN_RENDER_TIMEOUT_S`` so a short clip still gets startup headroom."""
    return max(MIN_RENDER_TIMEOUT_S, span_s * RENDER_REALTIME_FACTOR)


class DimensionMismatchError(RuntimeError):
    """Rendered clip is not exactly target_w × target_h (fail-closed)."""


class RenderOutputError(RuntimeError):
    """ffmpeg returned 0 but produced a missing/empty output file (fail-closed)."""


class ClipDurationError(RuntimeError):
    """A clip span exceeds MAX_CLIP_DURATION_S (fail-closed)."""


class CropModeError(RuntimeError):
    """A render box is BLURPAD (fail-closed: blur-pad is permanently disabled).

    Founder mandate: the vertical reframe ALWAYS fills the frame with a 9:16 crop —
    speaker-tracked when a speaker exists, centered otherwise. Blur-pad is retired,
    so a ``BLURPAD_MODE`` box reaching the render path is a programming error, not a
    runtime choice — fail closed rather than silently emit a blur-padded clip.
    """


# ---- pure builders (unit-tested directly, no ffmpeg) ----


STACK_VIDEO_LABEL: str = "[v]"  # the named output of a STACK / CONTAIN (filter_complex) graph

# CONTAIN (b-roll full-frame) blurred-margin fill tuning. The bg leg is a strong
# Gaussian blur so the side/top bars read as ambient colour, not detail (the Opus
# Clip / Submagic look); the slight darken keeps the foreground frame the focus.
CONTAIN_BLUR_SIGMA: int = 24  # libavfilter gblur sigma (20-30 reads as ambient at 1080-wide)
CONTAIN_DARKEN: float = -0.12  # eq=brightness on the blurred bg (-0.10..-0.15 range)


def _crop_graph_for(box: CropBox, w: int, h: int) -> str:
    """The render graph for a segment — a CROP-family graph (never blur-pad).

    A ``BLURPAD_MODE`` box can never originate in the live path (``compute_crop_box`` /
    ``compute_contain_box`` only ever yield ``CROP_MODE``); reject it fail-closed so no
    path can blur-pad. A ``CONTAIN_LAYOUT`` box fits the WHOLE frame inside the target
    with a blurred cover-zoom margin fill (b-roll, nothing cropped out). A ``STACK_LAYOUT``
    box vstacks its per-speaker panels; any other ``CROP_MODE`` box is a single fill-crop.
    """
    if box.mode == BLURPAD_MODE:
        raise CropModeError(f"render box must be a crop, got {box.mode}")
    if box.layout == CONTAIN_LAYOUT:
        return _build_contain_filtergraph(box, w, h)
    if box.layout == STACK_LAYOUT:
        return _build_stack_filtergraph(box, w, h)
    return _build_crop_filtergraph(box, w, h)


def _build_contain_filtergraph(box: CropBox, w: int, h: int) -> str:
    """Full-frame CONTAIN graph: fit the whole frame + blurred cover-zoom margin fill.

    For b-roll / GENERAL segments nothing may be cropped out (founder: "чтобы всё
    входило"). The input is split: the BG branch scale-COVERs the target then crops the
    overflow (the slight zoom that fills the frame) and is heavily blurred + darkened so
    the margins read as ambient colour; the FG branch scale-CONTAINs (the whole frame,
    letterboxed) and is overlaid centred. ``setsar=1`` is applied AFTER the overlay so
    the composite ships SQUARE pixels (SAR 1:1 / DAR 9:16) — applying it only to the FG
    leg leaves the output with a non-square SAR and the wrong display ratio. Output is
    EXACTLY ``w``×``h`` (the fixed even scale targets), yuv420p-safe. ``box`` describes
    the whole source frame; its dims are not referenced here (the fit is target-driven).
    """
    return (
        f"[0:v]split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={CONTAIN_BLUR_SIGMA},eq=brightness={CONTAIN_DARKEN}[bg2];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1{STACK_VIDEO_LABEL}"
    )


def _build_crop_filtergraph(box: CropBox, w: int, h: int) -> str:
    """Fill-crop graph: crop the 9:16 column, scale to target, square pixels.

    This is the single-window render path (founder mandate: always a 9:16 fill-crop). A
    TRACK box crops the speaker column; a GENERAL box crops the center column. Both
    scale to ``w``×``h`` and fill the frame edge-to-edge — no blur, no side bars.
    """
    return f"crop={box.w}:{box.h}:{box.x}:{box.y},scale={w}:{h},setsar=1"


def _build_stack_filtergraph(box: CropBox, w: int, h: int) -> str:
    """Split-screen graph: crop each panel → scale to an equal-height tile → vstack.

    ``n`` panels stack to ``w``×``h`` with tile height ``h // n`` (even). Each panel is
    cropped from input 0 and scaled to ``w × tile_h``; ``vstack`` joins them top→bottom
    into the named ``[v]`` output. Because each panel window is ALREADY exactly
    ``w:(h/n)`` (the geometry leg's discipline), the scale is distortion-free. Fail-closed:
    fewer than two panels, or a target height not evenly tileable, raises ``CropModeError``.
    """
    n = len(box.panels)
    if n < 2:
        raise CropModeError(f"STACK layout needs >=2 panels, got {n}")
    tile_h = h // n
    if tile_h * n != h:
        raise CropModeError(f"target height {h} not evenly tileable into {n} panels")
    chains = [
        f"[0:v]crop={p.w}:{p.h}:{p.x}:{p.y},scale={w}:{tile_h},setsar=1[s{i}]"
        for i, p in enumerate(box.panels)
    ]
    inputs = "".join(f"[s{i}]" for i in range(n))
    return ";".join(chains) + f";{inputs}vstack=inputs={n}{STACK_VIDEO_LABEL}"


def _video_filter_args(box: CropBox, w: int, h: int) -> list[str]:
    """The ffmpeg video-filter tokens for ``box``: simple ``-vf`` or labelled ``-filter_complex``.

    A single-window crop is one chain → ``-vf graph`` (ffmpeg auto-maps the lone output).
    A ``STACK_LAYOUT`` (vstack) or ``CONTAIN_LAYOUT`` (split/overlay) graph names its
    output ``[v]`` and uses multi-input filters, so it needs ``-filter_complex graph -map
    [v]`` to select the composited video stream.
    """
    graph = _crop_graph_for(box, w, h)
    if box.layout in (STACK_LAYOUT, CONTAIN_LAYOUT):
        return ["-filter_complex", graph, "-map", STACK_VIDEO_LABEL]
    return ["-vf", graph]


def _audio_map_args(box: CropBox) -> list[str]:
    """Explicit source-audio map for a STACK/CONTAIN render; empty for a single ``-vf`` crop.

    A ``-filter_complex`` graph names its video output, so the source audio is no longer
    auto-mapped — add ``-map 0:a:0?`` (the ``?`` keeps a silent source from failing).
    A single-window ``-vf`` render auto-maps audio, so it needs nothing here.
    """
    return ["-map", "0:a:0?"] if box.layout in (STACK_LAYOUT, CONTAIN_LAYOUT) else []


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
        *_video_filter_args(box, w, h),
        *_audio_map_args(box),
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
        # Output goes to a `*.mp4.partial` temp path (atomic rename), whose
        # `.partial` suffix hides the extension from ffmpeg's muxer probe — pin
        # the format explicitly so it never fails with "Unable to choose an
        # output format".
        "-f",
        "mp4",
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
        *_video_filter_args(box, w, h),
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
        # Output goes to a `*.mp4.partial` temp path (atomic rename), whose
        # `.partial` suffix hides the extension from ffmpeg's muxer probe — pin
        # the format explicitly so it never fails with "Unable to choose an
        # output format".
        "-f",
        "mp4",
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
        # Output goes to a `*.mp4.partial` temp path (atomic rename), whose
        # `.partial` suffix hides the extension from ffmpeg's muxer probe — pin
        # the format explicitly so it never fails with "Unable to choose an
        # output format".
        "-f",
        "mp4",
        str(out),
    ]


def _write_concat_list(text: str) -> Path:
    """Write a concat-demuxer list to a temp file and return its path (covered helper)."""
    fd, name = tempfile.mkstemp(suffix=".txt", prefix="fh_concat_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(text)
    return Path(name)


# ---- impure seams ----


def _run_ffmpeg(argv: list[str], span_s: float) -> None:  # pragma: no cover - ffmpeg boundary
    """Run an ffmpeg argv with a span-scaled timeout + captured stderr.

    A hung encode is killed at ``_timeout_for(span)`` (``TimeoutExpired`` →
    retryable upstream); a non-zero exit becomes a fail-closed ``RenderOutputError``
    carrying the tail of stderr, so the failing ffmpeg line reaches the logs.
    """
    try:
        subprocess.run(
            argv, check=True, capture_output=True, text=True, timeout=_timeout_for(span_s)
        )
    except subprocess.CalledProcessError as exc:
        raise RenderOutputError(
            f"ffmpeg failed (rc={exc.returncode}): {(exc.stderr or '')[-2000:]}"
        ) from exc


def _run_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one delivery clip (the only ffmpeg call). Argv is built/tested purely."""
    _run_ffmpeg(_build_render_argv(src, start, end, box, out, w, h, bitrate), end - start)


def _run_video_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one VIDEO-ONLY reframe segment. Argv is built/tested purely."""
    _run_ffmpeg(_build_video_render_argv(src, start, end, box, out, w, h, bitrate), end - start)


def _run_concat_mux_ffmpeg(
    parts: Sequence[Path], src: str, start: float, end: float, out: Path
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Concat video parts + one audio cut → final mp4. List build/argv tested purely."""
    list_path = _write_concat_list(_build_concat_list(parts))
    try:
        _run_ffmpeg(_build_concat_mux_argv(list_path, src, start, end, out), end - start)
    finally:
        list_path.unlink(missing_ok=True)


def _write_manifest_json(path: Path, data: dict[str, object]) -> None:
    """Write the manifest dict as pretty UTF-8 JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:  # pragma: no cover - wall clock, injected in tests
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_caption_band(src: str, start: float, end: float) -> None:
    """Feature-flag default: source-caption detection OFF (records None)."""
    return None


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


@dataclass(frozen=True)
class _RenderContext:
    """The per-job render seams + params, shared by every parallel clip worker."""

    src_path: str
    out_dir: Path
    scene_cut_times: Sequence[float]
    target_w: int
    target_h: int
    bitrate: str
    selector: SpeakerRegionSelector
    render_fn: RenderFn
    video_render_fn: VideoRenderFn
    concat_mux_fn: ConcatMuxFn
    probe_fn: ProbeFn
    caption_band_fn: CaptionBandFn
    replace_fn: ReplaceFn


def _render_one_clip(rank: int, clip: SelectedClip, ctx: _RenderContext) -> ClipEntry:
    """Render ONE ranked clip to its ``clip_NN.mp4`` and return its immutable ``ClipEntry``.

    Pure w.r.t. shared state: writes only its own per-rank files and returns a new
    ``ClipEntry`` — never appends to a shared list — so the workers can run in
    parallel and the caller assembles results in rank order. Fail-closed on bad
    span / >180 s / empty output / probe mismatch.
    """
    start = clip.candidate.start_time
    end = clip.candidate.end_time
    span = end - start
    if span <= 0:
        raise ValueError(f"clip span must be positive, got [{start}, {end}]")
    if span > MAX_CLIP_DURATION_S:
        raise ClipDurationError(f"clip span {span}s exceeds cap {MAX_CLIP_DURATION_S}s")

    traj = ctx.selector.select_speaker_region(ctx.src_path, start, end, ctx.scene_cut_times)
    cuts_rel = [c - start for c in ctx.scene_cut_times if start <= c < end]
    segments = build_render_segments(traj, clip_duration=span, scene_cut_times=cuts_rel)

    out_path = ctx.out_dir / clip_filename(rank)
    # Render into a sibling ``*.partial`` (same dir → same fs → atomic rename),
    # verify it, THEN promote to the canonical name. A crash mid-encode leaves
    # only a ``.partial`` (swept with the workspace) — never a truncated clip a
    # cache check could mistake for a complete one.
    out_partial = out_path.with_name(out_path.name + ".partial")
    if len(segments) == 1:  # fast path — one render with audio (back-compat)
        ctx.render_fn(
            ctx.src_path,
            start,
            end,
            segments[0].box,
            out_partial,
            ctx.target_w,
            ctx.target_h,
            ctx.bitrate,
        )
    else:
        _render_segments(
            ctx.src_path,
            start,
            out_partial,
            segments,
            target_w=ctx.target_w,
            target_h=ctx.target_h,
            bitrate=ctx.bitrate,
            rank=rank,
            _video_render_fn=ctx.video_render_fn,
            _concat_mux_fn=ctx.concat_mux_fn,
            _probe_fn=ctx.probe_fn,
        )
    if not out_partial.exists() or out_partial.stat().st_size == 0:
        raise RenderOutputError(f"ffmpeg produced no output at {out_path}")
    rw, rh = ctx.probe_fn(out_partial)
    if (rw, rh) != (ctx.target_w, ctx.target_h):
        raise DimensionMismatchError(
            f"clip {rank} is {rw}x{rh}, expected {ctx.target_w}x{ctx.target_h}"
        )
    ctx.replace_fn(out_partial, out_path)

    band = ctx.caption_band_fn(ctx.src_path, start, end)
    return ClipEntry(
        rank=rank,
        score=clip.scored.aggregate,
        sub_scores=clip.scored.sub_scores,
        confidence=clip.scored.confidence,
        start_time=start,
        end_time=end,
        duration_s=round_duration(start, end),
        width=ctx.target_w,
        height=ctx.target_h,
        path=clip_filename(rank),
        title=clip.candidate.title,
        used_video=clip.used_video,
        model_used=clip.scored.model_used,
        modalities_used=clip.scored.modalities_used,
        segment_count=len(segments),
        caption_band=band.to_dict() if band is not None else None,
    )


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
    _caption_band_fn: CaptionBandFn = _no_caption_band,
    _replace_fn: ReplaceFn = os.replace,
    _map_fn: MapFn = strict_ordered_threadpool_map,
) -> RenderManifest:
    """Render the ranked cascade clips to vertical mp4s + ``manifest.json``.

    Each clip's trajectory is split into 9:16 fill-crop render segments (dynamic
    reframe — founder mandate: ALWAYS fill-crop, speaker-tracked when a speaker
    exists, centered otherwise, never blur-pad): a single-segment clip takes the
    fast path (one ``_render_fn`` with audio); a multi-segment clip renders each
    segment VIDEO-ONLY then concatenates them with ONE clip-wide audio cut (no
    per-segment A/V drift). The per-clip encodes run through a BOUNDED thread pool
    (``_map_fn``) — ffmpeg is process parallelism, so wall-clock drops ~Nx — and
    ``map`` preserves rank order, so the manifest is byte-identical to the sequential
    build. Fail-CLOSED: any clip that raises (bad span / >180 s / empty output /
    probe mismatch) propagates and aborts the whole render (a paid clip must never
    silently vanish). Empty clips → a valid manifest with ``clip_count=0`` and no
    ffmpeg call.
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    # Env-driven seam: GPU LR-ASD active-speaker lane when GPU_ASD_ENABLED is set +
    # configured, else the CPU YuNet/MediaPipe heuristic. Caller can still inject one.
    selector = selector or build_speaker_region_selector()

    ordered = sorted(clips, key=lambda c: c.rank)
    if [c.rank for c in ordered] != list(range(len(ordered))):
        raise RuntimeError(
            f"clip ranks are not a contiguous 0..n-1 set: {[c.rank for c in ordered]}"
        )

    ctx = _RenderContext(
        src_path=src_path,
        out_dir=out_dir,
        scene_cut_times=scene_cut_times,
        target_w=target_w,
        target_h=target_h,
        bitrate=bitrate,
        selector=selector,
        render_fn=_render_fn,
        video_render_fn=_video_render_fn,
        concat_mux_fn=_concat_mux_fn,
        probe_fn=_probe_fn,
        caption_band_fn=_caption_band_fn,
        replace_fn=_replace_fn,
    )
    # ``map`` preserves order → entries stay rank-sorted; fail-closed map re-raises.
    entries: list[ClipEntry] = list(
        _map_fn(lambda pair: _render_one_clip(pair[0], pair[1], ctx), list(enumerate(ordered)))
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
