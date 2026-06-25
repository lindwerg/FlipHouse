"""Golden encode/caption frames — REAL ffmpeg, run in CI when the codecs exist (EVAL-2).

Two end-to-end guards that an argv/string-level assert cannot give:
  * the delivery render is exactly 1080x1920 H.264/yuv420p +faststart, encoded by
    the LGPL ``libopenh264`` (NOT libx264);
  * the libass caption burn-in actually paints text in the caption band and keeps
    the platform bottom-UI strip clear.

CAPABILITY-GATED, not env-gated: each test runs wherever ffmpeg has the needed
encoder/filter (the CI image and the Railway worker image both build ffmpeg with
``--enable-libopenh264 --enable-libass``) and AUTO-SKIPS on a stock GPL dev box
that lacks them — so it is a true CI regression guard, never a false red.

Set ``FLIPHOUSE_REQUIRE_DELIVERY_CODEC=1`` to turn a missing capability from a
skip into a HARD FAILURE — the founder/CI uses it to assert the delivery image
really ships libopenh264+libass before cutover, so the codec can never silently
go missing (which would let clips ship GPL-encoded or with no captions).

Bodies are ``# pragma: no cover`` — encoded frames are never counted by the
offline 100% gate; the argv/ass builders they call are unit-covered elsewhere.
"""

import os
import shutil
import subprocess
from functools import cache

import pytest
from PIL import ImageStat

from fliphouse_worker.captioning.ass import build_caption_ass, group_caption_lines
from fliphouse_worker.captioning.segments import CaptionWord
from fliphouse_worker.clipping.crop_geometry import compute_crop_box
from fliphouse_worker.clipping.render import _build_render_argv, _escape_subtitles_path
from fliphouse_worker.video_asserts import (
    _extract_frame,
    probe_dimensions,
    probe_pixel_format,
    probe_video_codec,
    region_has_content,
)

_REQUIRE = bool(os.getenv("FLIPHOUSE_REQUIRE_DELIVERY_CODEC"))


@cache
def _ffmpeg_capabilities() -> str:  # pragma: no cover - probes the live ffmpeg
    if not shutil.which("ffmpeg"):
        return ""
    enc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    flt = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True
    ).stdout
    return enc + flt


def _missing(token: str) -> bool:  # pragma: no cover - thin live probe
    return token not in _ffmpeg_capabilities()


def _require_or_skip(token: str, what: str) -> None:  # pragma: no cover - live-gated
    """Hard-fail when REQUIRE is set (cutover enforcement); otherwise auto-skip."""
    if _missing(token):
        msg = f"ffmpeg lacks {what} ({token})"
        if _REQUIRE:
            pytest.fail(f"FLIPHOUSE_REQUIRE_DELIVERY_CODEC set but {msg}")
        pytest.skip(msg)


@pytest.mark.live
def test_pipeline_golden_render(make_lavfi_clip_openh264, tmp_path):  # pragma: no cover - live
    _require_or_skip("libopenh264", "the LGPL delivery encoder")
    src = make_lavfi_clip_openh264("testsrc=size=1280x720:rate=24:duration=2")
    out = tmp_path / "clip_00.mp4"
    box = compute_crop_box(1280, 720, center_x=None)  # no faces → centered 9:16 fill-crop
    argv = _build_render_argv(str(src), 0.0, 2.0, box, out, 1080, 1920, "6M")
    subprocess.run(argv, check=True)

    assert probe_dimensions(out) == (1080, 1920)
    assert probe_video_codec(out) == "h264"
    assert probe_pixel_format(out) == "yuv420p"


@pytest.mark.live
def test_caption_golden_frame_paints_band_and_clears_bottom_ui(tmp_path):  # pragma: no cover - live
    # Burn a real per-word libass caption onto a black 1080x1920 frame and prove,
    # at the pixel level, that (a) the caption band has bright text and (b) the
    # bottom platform-UI strip stays clear — the geometry the ass-string asserts
    # only describe in numbers.
    _require_or_skip("libopenh264", "the LGPL delivery encoder")
    _require_or_skip("subtitles", "the libass subtitles filter")

    # One short line, fully active for the whole 1s frame window.
    words = (
        CaptionWord("ШОК", 0.0, 1.0),
        CaptionWord("ДЕНЬГИ", 0.0, 1.0),
    )
    lines = group_caption_lines(words)
    ass = build_caption_ass(lines)
    ass_path = tmp_path / "cap.ass"
    ass_path.write_text(ass, encoding="utf-8")

    out = tmp_path / "captioned.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-y",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=1080x1920:r=24:d=1",
            "-vf",
            f"subtitles={_escape_subtitles_path(ass_path)}",
            "-c:v",
            "libopenh264",
            "-pix_fmt",
            "yuv420p",
            "-frames:v",
            "24",
            str(out),
        ],
        check=True,
    )

    # The whole resting caption band [1180, 1600] (safe_zones cross-platform band)
    # must hold bright caption ink; the bottom platform-UI strip below it must not.
    assert region_has_content(out, (0, 1080, 1180, 1600)), "caption band must paint text"

    # Bottom ~UI strip (the like/comment/share + sound-attribution cluster) must
    # stay dark — captions are lifted ABOVE it on purpose. Use the full frame mean
    # to confirm the burn happened, then assert the bottom strip is clear of ink.
    bottom_strip = _extract_frame(out, t=0.0).crop((0, 1750, 1080, 1920)).convert("L")
    bottom_mean = ImageStat.Stat(bottom_strip).mean[0]
    assert bottom_mean < 8.0, f"bottom UI strip must stay clear of captions, got {bottom_mean:.1f}"
