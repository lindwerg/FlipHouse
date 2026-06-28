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
import re
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
    SINGLE_LAYOUT,
    STACK_LAYOUT,
    TARGET_H,
    TARGET_W,
    CropBox,
    clip_filename,
    compute_contain_box_region,
    compute_fill_box_region,
    content_is_portrait,
    round_duration,
)
from .manifest import ENGINE_NAME, MANIFEST_SCHEMA_VERSION, ClipEntry, RenderManifest
from .punch import PunchZoom, PunchZoomError, punch_zoom_chain
from .segments import RenderSegment, build_render_segments, sanitize_scene_cuts
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
# cropdetect samples only a SHORT window at the head of a b-roll segment (cropdetect
# accumulates; the LAST emitted crop= is its settled estimate) — fast, and a bounded
# wall-clock cost per paid clip. The whole multi-second segment is NOT probed.
CROPDETECT_PROBE_S: float = 2.0

# Render one delivery clip with audio; the trailing ``Path | None`` is the optional
# per-clip ``.ass`` folded into the SAME encode (SPD-1 single-pass caption burn). The two
# OPTIONAL trailing args (``PunchZoom | None``, ``float | None`` src_fps) are the P3-A7
# punch-ON overload — ``typing.Callable`` can't express a defaulted trailing arg and there
# is no mypy gate, so the back-compat 9-positional-arg call (no punch) stays byte-identical.
RenderFn = Callable[
    [
        str,
        float,
        float,
        "CropBox",
        Path,
        int,
        int,
        str,
        "Path | None",
        "PunchZoom | None",
        "float | None",
    ],
    None,
]
# Video-only segment render (no audio) — same shape as RenderFn but the argv adds -an.
# Segments are caption-free; the clip-wide ``.ass`` is burned in the concat-mux step.
VideoRenderFn = Callable[[str, float, float, "CropBox", Path, int, int, str], None]
# Concatenate video parts + a SINGLE per-clip audio cut → one muxed mp4. The trailing
# ``Path | None`` is the optional clip-wide ``.ass`` burned in this pass (SPD-1).
ConcatMuxFn = Callable[[Sequence[Path], str, float, float, Path, "Path | None"], None]
ProbeFn = Callable[[Path], tuple[int, int]]
# Build the per-clip caption ``.ass`` text for a clip window given its (already detected)
# source caption band, or None when the clip has no in-window words (fail-open: an
# uncaptioned clip is acceptable). Injected by the reframe stage (real word_segments) —
# the default yields None (no captions, back-compat single-encode).
CaptionAssFn = Callable[[float, float, "dict[str, object] | None"], "str | None"]
# Detect the bar-stripped content region of a b-roll window: (src, abs_start, abs_end) →
# (x, y, w, h) of the detected content, or None when detection is inconclusive (fail-OPEN
# to the whole-frame CONTAIN box). The only fail-OPEN seam in this fail-closed render path.
CropDetectFn = Callable[[str, float, float], "tuple[int, int, int, int] | None"]
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


def _crop_graph_for(
    box: CropBox,
    w: int,
    h: int,
    punch: PunchZoom | None = None,
    src_fps: float | None = None,
) -> str:
    """The render graph for a segment — a CROP-family graph (never blur-pad).

    A ``BLURPAD_MODE`` box can never originate in the live path (``compute_crop_box`` /
    ``compute_contain_box`` only ever yield ``CROP_MODE``); reject it fail-closed so no
    path can blur-pad. A ``CONTAIN_LAYOUT`` box fits the WHOLE frame inside the target
    with a blurred cover-zoom margin fill (b-roll, nothing cropped out). A ``STACK_LAYOUT``
    box vstacks its per-speaker panels; any other ``CROP_MODE`` box is a single fill-crop.

    P3-A7: a non-None ``punch`` is valid ONLY for the single-window ``SINGLE_LAYOUT`` crop
    (a CONTAIN/STACK box never receives it — fail-closed defense-in-depth; the call site
    already passes ``None`` for those, so a valid b-roll renders punch-free, not raised).
    """
    if box.mode == BLURPAD_MODE:
        raise CropModeError(f"render box must be a crop, got {box.mode}")
    if punch is not None and box.layout != SINGLE_LAYOUT:
        raise PunchZoomError(f"punch-zoom is only valid for a SINGLE crop, got {box.layout}")
    if box.layout == CONTAIN_LAYOUT:
        return _build_contain_filtergraph(box, w, h)
    if box.layout == STACK_LAYOUT:
        return _build_stack_filtergraph(box, w, h)
    return _build_crop_filtergraph(box, w, h, punch, src_fps)


def _build_contain_filtergraph(box: CropBox, w: int, h: int) -> str:
    """Full-frame CONTAIN graph: fit the whole frame + blurred cover-zoom margin fill.

    For b-roll / GENERAL segments nothing may be cropped out (founder: "чтобы всё
    входило"). The graph LEADS with ``crop=box.w:box.h:box.x:box.y`` to strip any baked
    letterbox/pillarbox bars on the DETECTED content region — for the whole-frame fallback
    box (``box`` = the even source frame) that lead crop is a no-op, so behaviour matches
    the bar-free case exactly (regression-safe). The stripped region is then split: the BG
    branch scale-COVERs the target then crops the overflow (the slight zoom that fills the
    frame) and is heavily blurred + darkened so the margins read as ambient colour; the FG
    branch scale-CONTAINs (the whole region, letterboxed) and is overlaid centred.
    ``setsar=1`` is applied AFTER the overlay so the composite ships SQUARE pixels (SAR 1:1
    / DAR 9:16) — applying it only to the FG leg leaves a non-square SAR. Output is EXACTLY
    ``w``×``h`` (the fixed even scale targets), yuv420p-safe.
    """
    return (
        f"[0:v]crop={box.w}:{box.h}:{box.x}:{box.y},split=2[bg][fg];"
        f"[bg]scale={w}:{h}:force_original_aspect_ratio=increase,"
        f"crop={w}:{h},gblur=sigma={CONTAIN_BLUR_SIGMA},eq=brightness={CONTAIN_DARKEN}[bg2];"
        f"[fg]scale={w}:{h}:force_original_aspect_ratio=decrease[fg2];"
        f"[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1{STACK_VIDEO_LABEL}"
    )


def _build_crop_filtergraph(
    box: CropBox,
    w: int,
    h: int,
    punch: PunchZoom | None = None,
    src_fps: float | None = None,
) -> str:
    """Fill-crop graph: crop the 9:16 column, scale to target, square pixels.

    This is the single-window render path (founder mandate: always a 9:16 fill-crop). A
    TRACK box crops the speaker column; a GENERAL box crops the center column. Both
    scale to ``w``×``h`` and fill the frame edge-to-edge — no blur, no side bars.

    P3-A7: when ``punch`` is set the static ``scale={w}:{h}`` link is REPLACED by a single
    ``zoompan`` node (a time-varying center zoom onto the same fixed ``w``×``h`` canvas) —
    still ONE encode (SPD-1), still LGPL (zoompan is core libavfilter). When ``punch`` is
    None the node is OMITTED ENTIRELY (a Z=1 zoompan would be a visual no-op but an extra
    filter node → a different string), so the OFF graph is BYTE-IDENTICAL to the prior form.
    FAIL-CLOSED: a non-None ``punch`` with a missing/non-positive ``src_fps`` raises rather
    than emit a wrong-fps (desynced) zoompan.
    """
    if punch is None:
        scale_link = f"scale={w}:{h}"
    else:
        if src_fps is None or src_fps <= 0:
            raise PunchZoomError(f"punch-zoom requires a positive src_fps, got {src_fps}")
        scale_link = punch_zoom_chain(w, h, src_fps, punch)
    return f"crop={box.w}:{box.h}:{box.x}:{box.y},{scale_link},setsar=1"


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


def _escape_subtitles_path(ass_path: Path) -> str:
    """Escape an ``.ass`` path for the libass ``subtitles=`` filter value (``\\`` then ``:``).

    A raw ``:`` inside ``subtitles=<path>`` separates filter options, so a drive/dir
    colon would feed libass bogus option args; backslashes are doubled FIRST so the
    colon-escaping backslashes are not themselves doubled. Mirrors the (now retired)
    caption-burn escaper so the single-pass graph matches the old two-pass byte-for-byte.
    """
    return str(ass_path).replace("\\", "\\\\").replace(":", "\\:")


def _video_filter_args(
    box: CropBox,
    w: int,
    h: int,
    ass_path: Path | None = None,
    punch: PunchZoom | None = None,
    src_fps: float | None = None,
) -> list[str]:
    """The ffmpeg video-filter tokens for ``box``: simple ``-vf`` or labelled ``-filter_complex``.

    A single-window crop is one chain → ``-vf graph`` (ffmpeg auto-maps the lone output).
    A ``STACK_LAYOUT`` (vstack) or ``CONTAIN_LAYOUT`` (split/overlay) graph names its
    output ``[v]`` and uses multi-input filters, so it needs ``-filter_complex graph -map
    [v]`` to select the composited video stream.

    When ``ass_path`` is given the libass ``subtitles=`` filter is appended AS THE LAST
    link in the chain so captions rasterize onto the FINAL composited 1080×1920 frame —
    SPD-1: this is the single-encode fold (caption burn rides the reframe pass, no second
    libopenh264 re-encode). For the plain ``-vf`` crop it appends ``,subtitles=…``; for a
    ``-filter_complex`` graph the ``[v]`` output is piped into a trailing
    ``[v]subtitles=…[vout]`` link and ``[vout]`` is mapped instead.
    """
    graph = _crop_graph_for(box, w, h, punch, src_fps)
    if box.layout in (STACK_LAYOUT, CONTAIN_LAYOUT):
        if ass_path is not None:
            subs = f"subtitles={_escape_subtitles_path(ass_path)}"
            graph = f"{graph};{STACK_VIDEO_LABEL}{subs}[vout]"
            return ["-filter_complex", graph, "-map", "[vout]"]
        return ["-filter_complex", graph, "-map", STACK_VIDEO_LABEL]
    if ass_path is not None:
        graph = f"{graph},subtitles={_escape_subtitles_path(ass_path)}"
    return ["-vf", graph]


def _audio_map_args(box: CropBox) -> list[str]:
    """Explicit source-audio map for a STACK/CONTAIN render; empty for a single ``-vf`` crop.

    A ``-filter_complex`` graph names its video output, so the source audio is no longer
    auto-mapped — add ``-map 0:a:0?`` (the ``?`` keeps a silent source from failing).
    A single-window ``-vf`` render auto-maps audio, so it needs nothing here.
    """
    return ["-map", "0:a:0?"] if box.layout in (STACK_LAYOUT, CONTAIN_LAYOUT) else []


def _video_encoder_args(bitrate: str) -> list[str]:
    """The LGPL-clean libopenh264 video-codec block — the SINGLE delivery-encoder seam.

    Extracted (P3-B1) from the three argv builders that previously inlined an identical
    block, so the codec + its rate-control knobs live in ONE place. This is BYTE-IDENTICAL
    to the prior inline literals (proven by the argv goldens) and is the one seam B2 will
    later swap (``-c:v h264_nvenc``/``h264_videotoolbox`` behind a probe, libopenh264
    staying the guaranteed default + fallback).

    ``bitrate`` stays a PARAMETER (not a read of ``TARGET_BITRATE``) because the
    concat-mux builder passes a caller bitrate; hardcoding the constant would silently
    change that argv. libopenh264 is ABR-only — NO ``-crf``/``-rc_mode``/``-allow_skip_frames``
    (non-portable, deliberately omitted). NOTE (P3-B1 finding): an intra-clip ``-threads``
    tune was evaluated and REJECTED — the render loop already fans out
    ``MAX_RENDER_WORKERS=4`` native encoders on the 2-vCPU cpu-worker box (see
    ``concurrency.py``), so per-clip slice-threading only adds OpenH264 slice
    compression-efficiency loss with no spare cores to speed any single clip. The real
    encode-side speed lever is B2 (hardware encoder), not encoder args.
    """
    return [
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
    ]


def _audio_encoder_args() -> list[str]:
    """The AAC delivery-audio block — extracted (P3-B1), byte-identical to the inline form."""
    return ["-c:a", "aac", "-b:a", AUDIO_BITRATE, "-ar", "48000", "-ac", "2"]


def _build_render_argv(
    src: str,
    start: float,
    end: float,
    box: CropBox,
    out: Path,
    w: int,
    h: int,
    bitrate: str,
    ass_path: Path | None = None,
    punch: PunchZoom | None = None,
    src_fps: float | None = None,
) -> list[str]:
    """Build the full LGPL-clean ffmpeg argv. libopenh264 has NO ``-crf`` — use ABR.

    ``-ss`` before ``-i`` (fast accurate re-encode seek, mirrors cutter). ABR via
    ``-b:v``/``-maxrate``/``-bufsize`` (NOT ``-crf``, NOT the build-specific
    ``-rc_mode``). ``-maxrate`` > ``-b:v`` lets libopenh264 overshoot rather than
    drop frames; the build-specific ``-allow_skip_frames`` knob is NOT portable
    across ffmpeg builds (verified absent on a real install) so it is omitted.
    Output is a real seekable file (``+faststart`` needs one).

    SPD-1: when ``ass_path`` is given the libass ``subtitles=`` filter is folded into
    THIS pass's filtergraph so the captioned delivery clip is produced in ONE
    libopenh264 encode (the second caption-burn re-encode is retired). ``subtitles=``
    adds no GPL dependency, so the LGPL delivery invariant is untouched.
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
        *_video_filter_args(box, w, h, ass_path, punch, src_fps),
        *_audio_map_args(box),
        *_video_encoder_args(bitrate),
        *_audio_encoder_args(),
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
        *_video_encoder_args(bitrate),
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
    list_path: Path,
    src: str,
    start: float,
    end: float,
    out: Path,
    ass_path: Path | None = None,
    bitrate: str = TARGET_BITRATE,
) -> list[str]:
    """Concat the video parts + ONE clip-wide audio cut from ``src``.

    Input 0 is the concat-demuxer video; input 1 is the source seeked to the clip
    window (``-ss start`` … ``-t span``). ``-shortest`` + the single audio cut keep
    lips locked to sound regardless of how many video segments were joined.

    With NO ``ass_path`` the joined video is forwarded byte-for-byte (``-c:v copy``).
    With an ``ass_path`` (SPD-1 multi-segment caption fold) the joined video is
    re-encoded ONCE through libopenh264 with ``-vf subtitles=`` burned in — replacing
    the retired separate caption-burn encode (still one fewer total encode than before).
    The LGPL delivery invariant holds: libopenh264 + libass, no GPL dependency.
    """
    span = end - start
    if ass_path is not None:
        video_codec_args = [
            "-vf",
            f"subtitles={_escape_subtitles_path(ass_path)}",
            *_video_encoder_args(bitrate),
        ]
    else:
        video_codec_args = ["-c:v", "copy"]
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
        *video_codec_args,
        *_audio_encoder_args(),
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


# ---- content-aware b-roll reframe (deferred FILL-vs-CONTAIN decision) ----


_CROPDETECT_RE = re.compile(r"crop=(\d+):(\d+):(\d+):(\d+)")


def _parse_cropdetect(stderr: str) -> tuple[int, int, int, int] | None:
    """Parse the LAST ``crop=w:h:x:y`` line from ffmpeg cropdetect stderr → ``(x, y, w, h)``.

    cropdetect ACCUMULATES across the sampled window; the FINAL emitted ``crop=`` is its
    settled estimate, so the last match wins. ffmpeg prints ``crop=w:h:x:y`` (width, height,
    x, y); this returns the geometry as ``(x, y, w, h)`` to match the region constructors.
    Returns None on a parse failure (no ``crop=`` line / unusable stderr) — the caller then
    fails OPEN to the whole-frame CONTAIN box. PURE.
    """
    matches = _CROPDETECT_RE.findall(stderr)
    if not matches:
        return None
    cw, ch, cx, cy = (int(v) for v in matches[-1])
    return cx, cy, cw, ch


def _cropdetect_result(returncode: int, stderr: str) -> tuple[int, int, int, int] | None:
    """Map an ffmpeg cropdetect (returncode, stderr) to a region or None (fail-OPEN). PURE.

    A NON-ZERO return code is treated as INCONCLUSIVE — even a failed ffmpeg can emit a
    stale/partial ``crop=`` line, so trusting its stderr would ship a bad region. On rc==0
    the settled estimate is parsed via :func:`_parse_cropdetect` (which itself yields None on
    a parse miss). Either way None means the caller fails OPEN to the whole-frame CONTAIN box.
    """
    if returncode != 0:
        return None
    return _parse_cropdetect(stderr)


def _resolve_contain_box(
    box: CropBox, src_w: int, src_h: int, region: tuple[int, int, int, int] | None
) -> CropBox:
    """Refine ONE whole-frame CONTAIN box to a content-aware box from a detected region.

    ``region`` None (cropdetect inconclusive) → keep the whole-frame CONTAIN box exactly
    (regression-safe fail-open). Otherwise decide on the detected content aspect:
    portrait/near-vertical → a centered 9:16 FILL cover-crop (``SINGLE`` layout, flows
    through the plain ``-vf`` fill graph); landscape → CONTAIN the bar-STRIPPED region
    (``CONTAIN`` layout, blur-pad). Any geometry failure also falls back to the original
    whole-frame box rather than blow a paid render. PURE w.r.t. the injected region. PURE.
    """
    if region is None:
        return box
    cx, cy, cw, ch = region
    try:
        if content_is_portrait(cw, ch):
            return compute_fill_box_region(src_w, src_h, cx, cy, cw, ch)
        return compute_contain_box_region(src_w, src_h, cx, cy, cw, ch)
    except ValueError:
        return box  # fail-OPEN to whole-frame CONTAIN — never raise on a b-roll segment


def _resolve_contain_segments(
    segments: Sequence[RenderSegment],
    src_path: str,
    clip_start: float,
    src_w: int,
    src_h: int,
    cropdetect_fn: CropDetectFn,
) -> tuple[RenderSegment, ...]:
    """Resolve every CONTAIN segment's box content-aware AT RENDER TIME (src + window known).

    The pure segment builder emits a whole-frame CONTAIN box as the b-roll DEFAULT/intent;
    here — where the source path and the segment's absolute time window exist — each CONTAIN
    segment runs the injectable ``cropdetect_fn`` over a short head window and is refined to
    a FILL (vertical content) or bar-stripped CONTAIN (landscape) box. Non-CONTAIN segments
    (TRACK / STACK speaker crops) are passed through BYTE-IDENTICAL. Returns a NEW immutable
    segments tuple. Runs for BOTH the single-segment fast path and the multi-segment path.

    SPD-4: the early ``continue`` below is the FILL-skip guarantee — a talking-head clip
    that resolves to a TRACK/SINGLE fill-crop NEVER pays the ~2 s cropdetect probe; only a
    genuine CONTAIN (b-roll / landscape) segment runs it. ``test_speaker_clip_never_runs_
    cropdetect`` pins this. So no extra guard is needed; the cost is already paid only where
    it changes the output.
    """
    resolved: list[RenderSegment] = []
    for seg in segments:
        if seg.box.layout != CONTAIN_LAYOUT:  # SPD-4: FILL/TRACK clips skip the cropdetect probe
            resolved.append(seg)
            continue
        region = cropdetect_fn(src_path, clip_start + seg.start_s, clip_start + seg.end_s)
        new_box = _resolve_contain_box(seg.box, src_w, src_h, region)
        resolved.append(RenderSegment(seg.start_s, seg.end_s, new_box))
    return tuple(resolved)


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
    src: str,
    start: float,
    end: float,
    box: CropBox,
    out: Path,
    w: int,
    h: int,
    bitrate: str,
    ass_path: Path | None = None,
    punch: PunchZoom | None = None,
    src_fps: float | None = None,
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one delivery clip (the only ffmpeg call). Argv is built/tested purely.

    SPD-1: ``ass_path`` (when set) folds the libass caption burn into THIS encode.
    P3-A7: ``punch``/``src_fps`` (when set) emit the time-varying zoompan node in the SAME
    encode.
    """
    _run_ffmpeg(
        _build_render_argv(src, start, end, box, out, w, h, bitrate, ass_path, punch, src_fps),
        end - start,
    )


def _run_video_render_ffmpeg(
    src: str, start: float, end: float, box: CropBox, out: Path, w: int, h: int, bitrate: str
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Render one VIDEO-ONLY reframe segment. Argv is built/tested purely."""
    _run_ffmpeg(_build_video_render_argv(src, start, end, box, out, w, h, bitrate), end - start)


def _run_concat_mux_ffmpeg(
    parts: Sequence[Path],
    src: str,
    start: float,
    end: float,
    out: Path,
    ass_path: Path | None = None,
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Concat video parts + one audio cut → final mp4. List build/argv tested purely.

    SPD-1: ``ass_path`` (when set) burns the clip-wide captions in THIS concat pass.
    """
    list_path = _write_concat_list(_build_concat_list(parts))
    try:
        _run_ffmpeg(_build_concat_mux_argv(list_path, src, start, end, out, ass_path), end - start)
    finally:
        list_path.unlink(missing_ok=True)


def _run_cropdetect(
    src: str, start: float, end: float
) -> tuple[int, int, int, int] | None:  # pragma: no cover - ffmpeg boundary
    """Detect the bar-stripped content region of a b-roll window via ffmpeg cropdetect.

    Samples a SHORT head window (``min(span, CROPDETECT_PROBE_S)``) with ``reset=0`` so
    cropdetect accumulates to a settled estimate, parses the LAST ``crop=`` line, and returns
    ``(x, y, w, h)``. Fails OPEN (returns None) on any ffmpeg error, a NON-ZERO return code
    (a failed ffmpeg can still emit a stale/partial ``crop=`` line), or a parse miss — a
    b-roll segment must never blow a paid render. The argv build + the (returncode, stderr)→
    region decision are pure (tested offline); only the subprocess here is impure.
    """
    span = min(end - start, CROPDETECT_PROBE_S)
    argv = [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-ss",
        f"{start}",
        "-i",
        src,
        "-t",
        f"{span}",
        "-vf",
        "cropdetect=limit=24:round=2:reset=0",
        "-f",
        "null",
        "-",
    ]
    try:
        proc = subprocess.run(argv, capture_output=True, text=True, timeout=_timeout_for(span))
    except (subprocess.SubprocessError, OSError):
        return None
    return _cropdetect_result(proc.returncode, proc.stderr or "")


def _write_manifest_json(path: Path, data: dict[str, object]) -> None:
    """Write the manifest dict as pretty UTF-8 JSON."""
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _utc_now_iso() -> str:  # pragma: no cover - wall clock, injected in tests
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _no_caption_band(src: str, start: float, end: float) -> None:
    """Feature-flag default: source-caption detection OFF (records None)."""
    return None


def _no_caption_ass(start: float, end: float, band: dict[str, object] | None) -> None:
    """Default ``CaptionAssFn``: no burned-in captions (back-compat single-encode).

    The reframe stage injects a real one (built from ``word_segments``); when unset the
    renderer produces uncaptioned clips exactly as before SPD-1 (golden-stable)."""
    return None


def _write_caption_ass(ass_text: str) -> Path:
    """Write per-clip ``.ass`` text to a temp file and return its path (covered helper).

    The file is removed by the caller in a ``finally`` once the encode that reads it has
    finished, so a crash never leaks it. Suffix is ``.ass`` so libass autodetects it.
    """
    fd, name = tempfile.mkstemp(suffix=".ass", prefix="fh_clip_caption_")
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(ass_text)
    return Path(name)


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
    ass_path: Path | None,
    _video_render_fn: VideoRenderFn,
    _concat_mux_fn: ConcatMuxFn,
    _probe_fn: ProbeFn,
) -> None:
    """Render each reframe segment VIDEO-ONLY (fail-closed per part), then concat +
    one clip-wide audio cut. Segment temp dir lives OUTSIDE out_dir and is swept.

    SPD-1: ``ass_path`` (when set) is burned into the clip in the concat-mux pass, so a
    multi-segment clip pays N video-only segment encodes + ONE captioned concat encode —
    one fewer total encode than the retired reframe-then-caption-restream two-pass."""
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
        _concat_mux_fn(parts, src_path, start, end, out_path, ass_path)
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
    cropdetect_fn: CropDetectFn
    caption_band_fn: CaptionBandFn
    caption_ass_fn: CaptionAssFn
    replace_fn: ReplaceFn
    # P3-A7 — OFF by default: the live reframe wiring passes neither, so every clip renders
    # byte-identical until a job opts in. ``punch_zoom`` is the hook envelope; ``src_fps`` is
    # the source frame rate zoompan needs (required, positive, only when ``punch_zoom`` set).
    punch_zoom: PunchZoom | None = None
    src_fps: float | None = None


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

    # P3-C5: clean untrusted scene cuts ONCE at the trust boundary, so both the smoothing
    # leg and the segment leg consume the same sorted/in-range/finite times (garbage → ()).
    cuts = sanitize_scene_cuts(ctx.scene_cut_times, start, end)
    traj = ctx.selector.select_speaker_region(ctx.src_path, start, end, cuts)
    cuts_rel = [c - start for c in cuts]
    segments = build_render_segments(traj, clip_duration=span, scene_cut_times=cuts_rel)
    # Refine b-roll CONTAIN boxes content-aware (src + window known here): vertical content
    # → FILL, landscape → bar-stripped CONTAIN, inconclusive → whole-frame CONTAIN (fail-open).
    segments = _resolve_contain_segments(
        segments, ctx.src_path, start, traj.source_width, traj.source_height, ctx.cropdetect_fn
    )

    out_path = ctx.out_dir / clip_filename(rank)
    # Render into a sibling ``*.partial`` (same dir → same fs → atomic rename),
    # verify it, THEN promote to the canonical name. A crash mid-encode leaves
    # only a ``.partial`` (swept with the workspace) — never a truncated clip a
    # cache check could mistake for a complete one.
    out_partial = out_path.with_name(out_path.name + ".partial")
    # SPD-1: detect the source caption band, then build this clip's per-word ``.ass``
    # ONCE and burn it in the SAME reframe encode (no second libopenh264 caption pass).
    # ``caption_ass_fn`` defaults to None (back-compat uncaptioned render); the reframe
    # stage injects the real word_segments builder. A clip with no in-window words yields
    # None → an uncaptioned clip (fail-open). The temp ``.ass`` is swept after the encode.
    band = ctx.caption_band_fn(ctx.src_path, start, end)
    band_dict = band.to_dict() if band is not None else None
    ass_text = ctx.caption_ass_fn(start, end, band_dict)
    ass_path = _write_caption_ass(ass_text) if ass_text is not None else None
    # P3-A7: punch is valid ONLY for a single-segment SINGLE_LAYOUT clip (a b-roll CONTAIN /
    # split STACK clip renders punch-free — semantically correct, not a raise).
    clip_punch = (
        ctx.punch_zoom if (len(segments) == 1 and segments[0].box.layout == SINGLE_LAYOUT) else None
    )
    try:
        if len(segments) == 1:  # fast path — one render with audio (back-compat)
            if clip_punch is None:
                ctx.render_fn(
                    ctx.src_path,
                    start,
                    end,
                    segments[0].box,
                    out_partial,
                    ctx.target_w,
                    ctx.target_h,
                    ctx.bitrate,
                    ass_path,
                )  # legacy 9-positional-arg shape → byte-identical OFF call
            else:
                ctx.render_fn(
                    ctx.src_path,
                    start,
                    end,
                    segments[0].box,
                    out_partial,
                    ctx.target_w,
                    ctx.target_h,
                    ctx.bitrate,
                    ass_path,
                    clip_punch,
                    ctx.src_fps,
                )  # punch-ON shape
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
                ass_path=ass_path,
                _video_render_fn=ctx.video_render_fn,
                _concat_mux_fn=ctx.concat_mux_fn,
                _probe_fn=ctx.probe_fn,
            )
    finally:
        if ass_path is not None:
            ass_path.unlink(missing_ok=True)
    if not out_partial.exists() or out_partial.stat().st_size == 0:
        raise RenderOutputError(f"ffmpeg produced no output at {out_path}")
    rw, rh = ctx.probe_fn(out_partial)
    if (rw, rh) != (ctx.target_w, ctx.target_h):
        raise DimensionMismatchError(
            f"clip {rank} is {rw}x{rh}, expected {ctx.target_w}x{ctx.target_h}"
        )
    ctx.replace_fn(out_partial, out_path)

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
    _cropdetect_fn: CropDetectFn = _run_cropdetect,
    _write_fn: WriteFn = _write_manifest_json,
    _clock: ClockFn = _utc_now_iso,
    _caption_band_fn: CaptionBandFn = _no_caption_band,
    _caption_ass_fn: CaptionAssFn = _no_caption_ass,
    _replace_fn: ReplaceFn = os.replace,
    _map_fn: MapFn = strict_ordered_threadpool_map,
    _punch_zoom: PunchZoom | None = None,
    _src_fps: float | None = None,
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
        cropdetect_fn=_cropdetect_fn,
        caption_band_fn=_caption_band_fn,
        caption_ass_fn=_caption_ass_fn,
        replace_fn=_replace_fn,
        punch_zoom=_punch_zoom,
        src_fps=_src_fps,
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
