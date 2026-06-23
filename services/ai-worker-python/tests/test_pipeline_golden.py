"""Live golden: a real libopenh264 render is exactly 1080x1920 H.264/yuv420p +faststart.

Triple-gated so it never runs in CI / on the GPL dev box (which lacks libopenh264):
  1. module skipif on FLIPHOUSE_LIVE_RENDER (mirrors test_live_gemini_eval.py),
  2. the `live` marker,
  3. an encoder-probe skipif that auto-skips (not errors) without libopenh264.
The founder runs this once on a libopenh264-equipped ffmpeg (the Railway image)
before cutover. Body is # pragma: no cover — never counted by the offline gate.
"""

import os
import shutil
import subprocess

import pytest

from fliphouse_worker.clipping.crop_geometry import compute_crop_box
from fliphouse_worker.clipping.render import _build_render_argv
from fliphouse_worker.video_asserts import (
    probe_dimensions,
    probe_pixel_format,
    probe_video_codec,
)

pytestmark = pytest.mark.skipif(
    not os.getenv("FLIPHOUSE_LIVE_RENDER"),
    reason="live render — set FLIPHOUSE_LIVE_RENDER=1 (needs a libopenh264 ffmpeg)",
)


def _has_libopenh264() -> bool:  # pragma: no cover - live-gated
    if not shutil.which("ffmpeg"):
        return False
    out = subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"], capture_output=True, text=True
    ).stdout
    return "libopenh264" in out


@pytest.mark.live
@pytest.mark.skipif(not _has_libopenh264(), reason="ffmpeg lacks libopenh264")
def test_pipeline_golden_render(make_lavfi_clip_openh264, tmp_path):  # pragma: no cover - live
    src = make_lavfi_clip_openh264("testsrc=size=1280x720:rate=24:duration=2")
    out = tmp_path / "clip_00.mp4"
    box = compute_crop_box(1280, 720, center_x=None)  # no faces → centered 9:16 fill-crop
    argv = _build_render_argv(str(src), 0.0, 2.0, box, out, 1080, 1920, "6M")
    subprocess.run(argv, check=True)

    assert probe_dimensions(out) == (1080, 1920)
    assert probe_video_codec(out) == "h264"
    assert probe_pixel_format(out) == "yuv420p"
