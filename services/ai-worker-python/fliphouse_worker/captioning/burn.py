"""Caption burn-in ffmpeg seam — mirror of ``clipping/render._run_ffmpeg``.

ONE LGPL-clean ffmpeg pass burns the ``.ass`` into the reframed clip via the
libass ``subtitles=`` filter: ``-c:v libopenh264`` (NEVER libx264 — the LGPL
invariant), ``-c:a copy`` (the clip is already cut to ``t=0`` with the right
audio, so audio is forwarded verbatim — no re-encode, no A/V drift), and NO
``-ss``/``-t`` (re-cutting would desync the captions). The argv is built/tested
PURELY; the only impure boundary (``_run_caption_burn``) is ``# pragma: no
cover`` and exercised only by the live golden, exactly like ``render.py``.

The subtitles filter value needs ``:`` and ``\\`` escaped — a raw ``:`` inside
``subtitles=<path>`` separates filter options, so a path with a colon would feed
libass garbage option args.
"""

from __future__ import annotations

import os
import subprocess  # noqa: S404 - same vetted ffmpeg boundary as clipping/render
import tempfile
from pathlib import Path

from ..clipping.render import RenderOutputError, _timeout_for

TARGET_BITRATE: str = "6M"
MAXRATE: str = "8M"
BUFSIZE: str = "12M"
GOP: int = 60


def _escape_subtitles_path(ass_path: Path) -> str:
    """Escape a path for the ``subtitles=`` filter value (``\\`` then ``:``).

    Backslashes are doubled first, then every ``:`` is backslash-escaped, so the
    filter argument parser reads the whole path as the filename rather than
    splitting on a drive/dir colon into bogus filter options.
    """
    return str(ass_path).replace("\\", "\\\\").replace(":", "\\:")


def _build_caption_burn_argv(src: str, ass_path: Path, out: Path, w: int, h: int) -> list[str]:
    """Build the LGPL-clean burn argv. No ``-ss``/``-t`` (clip is already at t=0).

    ``-vf subtitles=<escaped ass>`` renders the karaoke captions onto the frame.
    libopenh264 has no ``-crf`` → ABR via ``-b:v``/``-maxrate``/``-bufsize``
    (mirrors ``render._build_render_argv``). ``w``/``h`` are accepted for parity
    with the renderer seam and to document the expected 1080×1920 target.
    """
    subtitles = _escape_subtitles_path(ass_path)
    return [
        "ffmpeg",
        "-hide_banner",
        "-nostdin",
        "-loglevel",
        "error",
        "-i",
        src,
        "-vf",
        f"subtitles={subtitles}",
        "-c:v",
        "libopenh264",
        "-b:v",
        TARGET_BITRATE,
        "-maxrate",
        MAXRATE,
        "-bufsize",
        BUFSIZE,
        "-g",
        str(GOP),
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "copy",
        "-movflags",
        "+faststart",
        # Output is a `*.mp4.partial` temp path (atomic rename); its `.partial`
        # suffix hides the extension from ffmpeg's muxer probe, so pin mp4
        # explicitly ("Unable to choose an output format" otherwise).
        "-f",
        "mp4",
        str(out),
    ]


def _run_caption_burn(
    src: Path, ass_text: str, out: Path, *, target_w: int = 1080, target_h: int = 1920
) -> None:  # pragma: no cover - thin ffmpeg boundary, exercised only by the live golden
    """Write ``ass_text`` to a temp ``.ass`` beside the work dir, then burn it in.

    The ASS temp file is removed in a ``finally`` so a crash mid-encode never
    leaks it. A non-zero ffmpeg exit becomes a fail-closed ``RenderOutputError``
    carrying the stderr tail (same contract as ``render._run_ffmpeg``).
    """
    fd, ass_name = tempfile.mkstemp(suffix=".ass", prefix="fh_caption_")
    ass_path = Path(ass_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(ass_text)
        argv = _build_caption_burn_argv(str(src), ass_path, out, target_w, target_h)
        span = _probe_span(src)
        try:
            subprocess.run(
                argv, check=True, capture_output=True, text=True, timeout=_timeout_for(span)
            )
        except subprocess.CalledProcessError as exc:
            raise RenderOutputError(
                f"caption burn failed (rc={exc.returncode}): {(exc.stderr or '')[-2000:]}"
            ) from exc
    finally:
        ass_path.unlink(missing_ok=True)


def _probe_span(src: Path) -> float:  # pragma: no cover - thin ffprobe boundary
    """Clip duration in seconds (used only to scale the burn timeout)."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=nw=1:nk=1",
            str(src),
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    try:
        return float(out)
    except ValueError:
        return 0.0
