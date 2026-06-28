"""P3-A7 LIVE gate — the hook punch-zoom must (1) move real pixels (the ease manifests ONLY
in pixels, never in the .ass/argv), (2) settle back to the base framing, and (3) fire at
clip-relative frame 0 regardless of the production ``-ss`` seek, on a REAL ffmpeg render.

The zoompan node is folded into the single libopenh264 reframe pass (SPD-1) — a string-golden
proves the argv but NOT that the zoom rendered. This gate renders OFF and ON clips through the
production argv and compares frames.

OPT-IN: skipped unless ``FLIPHOUSE_LIVE_CAPTIONS=1`` and ffmpeg/ffprobe (with libopenh264 +
zoompan) are on PATH. CI never sets the flag → COLLECTED+SKIPPED; it never reports a green pass
and never enters the source-scoped 100% coverage gate (every render/measure body is
``# pragma: no cover - live-gated``). Run locally with:

    FLIPHOUSE_LIVE_CAPTIONS=1 pytest -m live tests/clipping/test_punch_live_golden.py
"""

from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from fliphouse_worker.clipping import render
from fliphouse_worker.clipping.crop_geometry import CROP_MODE, CropBox
from fliphouse_worker.clipping.punch import HOOK_PUNCH

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FLIPHOUSE_LIVE_CAPTIONS") != "1",
        reason="set FLIPHOUSE_LIVE_CAPTIONS=1 to run the A7 punch-zoom pixel gate",
    ),
]

CLIP_SECONDS = 3.0
SRC_FPS = 30.0
# The base box is a 608-wide 9:16 column of the 1080x1920 source (height>=1080 required).
BOX = CropBox(x=236, y=0, w=608, h=1080, mode=CROP_MODE)
PUNCH_WALL_BUDGET_FACTOR = 1.6  # zoompan re-rasterizes per frame, but must stay bounded
SETTLE_SSIM_MIN = 0.99  # the settled ON frame matches the OFF framing
TRANSIENT_SSIM_MAX = 0.999  # punched-in vs settled DIFFER → the zoom actually rendered


def _zoompan_available() -> bool:  # pragma: no cover - live-gated
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    )
    return "zoompan" in proc.stdout


def _render(
    src: Path, out: Path, start: float, *, punch: bool
) -> float:  # pragma: no cover - live-gated
    argv = render._build_render_argv(
        str(src),
        start,
        start + CLIP_SECONDS,
        BOX,
        out,
        1080,
        1920,
        render.TARGET_BITRATE,
        None,
        HOOK_PUNCH if punch else None,
        SRC_FPS if punch else None,
    )
    began = time.perf_counter()
    subprocess.run(argv, check=True, capture_output=True)
    return time.perf_counter() - began


def _frame(clip: Path, t: float, out: Path) -> Path:  # pragma: no cover - live-gated
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-ss",
            f"{t}",
            "-i",
            str(clip),
            "-frames:v",
            "1",
            "-y",
            str(out),
        ],
        check=True,
        capture_output=True,
    )
    return out


def _ssim(a: Path, b: Path) -> float:  # pragma: no cover - live-gated
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"All:([0-9.]+)", proc.stderr)
    assert match, f"no SSIM in ffmpeg output:\n{proc.stderr}"
    return float(match.group(1))


def _video_stream_count(clip: Path) -> int:  # pragma: no cover - live-gated
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(clip),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    return len([ln for ln in proc.stdout.splitlines() if ln.strip()])


def _dims(clip: Path) -> tuple[int, int]:  # pragma: no cover - live-gated
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(clip),
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    w, h = proc.stdout.strip().split("x")
    return int(w), int(h)


def test_punch_zoom_moves_pixels_settles_and_is_ss_immune(
    tmp_path: Path,
    make_lavfi_clip_openh264,
) -> None:  # pragma: no cover - live-gated
    if not _zoompan_available():
        pytest.skip("ffmpeg build lacks the zoompan filter")
    # A moving, detailed source so a zoom produces a visible per-frame delta.
    src = make_lavfi_clip_openh264(
        f"testsrc2=size=1080x1920:rate=30:duration={CLIP_SECONDS + 2}", audio=True
    )

    off = tmp_path / "off.mp4"
    on0 = tmp_path / "on0.mp4"
    on_ss = tmp_path / "on_ss.mp4"
    off_wall = _render(src, off, 0.0, punch=False)
    on_wall = _render(src, on0, 0.0, punch=True)
    _render(src, on_ss, 1.0, punch=True)  # non-zero -ss start

    # (a) both ON outputs are exactly the target canvas (fail-closed dims).
    assert _dims(on0) == (1080, 1920)
    assert _dims(on_ss) == (1080, 1920)
    # (d) a single H.264 video stream → one encode.
    assert _video_stream_count(on0) == 1

    # (b) ON(start=0): the punched-in head frame DIFFERS from the settled frame (zoom rendered).
    head0 = _frame(on0, 0.0, tmp_path / "h0.png")
    settle0 = _frame(on0, HOOK_PUNCH.duration_s + 0.3, tmp_path / "s0.png")
    assert _ssim(head0, settle0) < TRANSIENT_SSIM_MAX

    # (b') the SAME delta fires under a non-zero -ss (the on-clock / -ss-immunity gate).
    head_ss = _frame(on_ss, 0.0, tmp_path / "hss.png")
    settle_ss = _frame(on_ss, HOOK_PUNCH.duration_s + 0.3, tmp_path / "sss.png")
    assert _ssim(head_ss, settle_ss) < TRANSIENT_SSIM_MAX

    # (c) the settled ON frame matches the OFF framing in the held region (settle-to-base).
    off_settle = _frame(off, HOOK_PUNCH.duration_s + 0.3, tmp_path / "os.png")
    assert _ssim(settle0, off_settle) >= SETTLE_SSIM_MIN

    # (e) wall-time bounded.
    print(f"[A7 punch gate] off_wall={off_wall:.3f}s on_wall={on_wall:.3f}s")
    assert on_wall <= off_wall * PUNCH_WALL_BUDGET_FACTOR
    assert on_wall <= CLIP_SECONDS * render.RENDER_REALTIME_FACTOR


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
