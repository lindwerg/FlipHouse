"""P3-A6 LIVE gate — the contrast band must actually DARKEN the area behind the text on a
REAL libass+ffmpeg render.

The band is a pure ASS Style-row knob (BorderStyle=3 opaque/translucent box) folded into the
single libopenh264 reframe pass (SPD-1) — a byte-diff of the ``.ass`` proves the Style row
changed but NOT that libass rasterized a darker box behind the glyphs. This gate renders the
DEFAULT and band presets through the production argv over a WHITE source and asserts the mean
luma of a tight strip on the caption baseline drops for the band looks.

OPT-IN: skipped unless ``FLIPHOUSE_LIVE_CAPTIONS=1`` and ffmpeg/ffprobe (with libopenh264 +
libass + the ``signalstats`` filter) are on PATH. CI never sets the flag → COLLECTED+SKIPPED;
it never reports a green pass and never enters the source-scoped 100% coverage gate (every
render/measure body is ``# pragma: no cover - live-gated``). Run locally with:

    FLIPHOUSE_LIVE_CAPTIONS=1 pytest -m live tests/captioning/test_contrast_band_live_golden.py
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from fliphouse_worker.captioning.ass import (
    CONTRAST_BAND_BS3,
    CONTRAST_BAND_TRANSLUCENT,
    DEFAULT_PRESET,
    CaptionLine,
    build_caption_ass,
    group_caption_lines,
)
from fliphouse_worker.captioning.preset import CaptionPreset
from fliphouse_worker.captioning.segments import CaptionWord
from fliphouse_worker.clipping import render
from fliphouse_worker.clipping.crop_geometry import CROP_MODE, CropBox

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FLIPHOUSE_LIVE_CAPTIONS") != "1",
        reason="set FLIPHOUSE_LIVE_CAPTIONS=1 to run the A6 contrast-band luma gate",
    ),
]

CLIP_SECONDS = 3.0
# A tight strip on the caption baseline (MarginV=430 → band bottom at y=1920-430=1490),
# centred horizontally where the text box sits, so the crop is guaranteed to overlap the box.
BAND_CROP = "crop=560:180:260:1300"
# An opaque near-black box over a white background must drop mean luma well past this.
OPAQUE_LUMA_DROP = 60.0
# A ~50%-alpha box drops less, but if a build ignores box alpha it fails SAFE to opaque
# (still a positive drop) — never to "no band".
TRANSLUCENT_MIN_LUMA_DROP = 8.0


def _words() -> tuple[CaptionWord, ...]:  # pragma: no cover - live-gated
    spans = [
        ("контраст", 0.0, 1.0),
        ("band", 1.0, 2.0),
        ("тест", 2.0, CLIP_SECONDS),
    ]
    return tuple(CaptionWord(text=t, start=s, end=e) for t, s, e in spans)


def _write_ass(path: Path, preset: CaptionPreset) -> Path:  # pragma: no cover - live-gated
    lines: list[CaptionLine] = group_caption_lines(_words())
    path.write_text(build_caption_ass(lines, preset=preset), encoding="utf-8")
    return path


def _render(src: Path, ass_path: Path, out: Path) -> Path:  # pragma: no cover - live-gated
    box = CropBox(x=0, y=0, w=1080, h=1920, mode=CROP_MODE)
    argv = render._build_render_argv(
        str(src), 0.0, CLIP_SECONDS, box, out, 1080, 1920, render.TARGET_BITRATE, ass_path
    )
    subprocess.run(argv, check=True, capture_output=True)
    return out


def _signalstats_available() -> bool:  # pragma: no cover - live-gated
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-filters"], capture_output=True, text=True, check=True
    )
    return "signalstats" in proc.stdout


def _mid_frame_yavg(mp4: Path) -> float:  # pragma: no cover - live-gated
    """Mean luma (Y) of BAND_CROP on the first frame, via the lavfi movie+signalstats graph."""
    graph = f"movie='{mp4}',{BAND_CROP},signalstats"
    proc = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            graph,
            "-show_entries",
            "frame_tags=lavfi.signalstats.YAVG",
            "-of",
            "default=nw=1:nk=1",
            "-read_intervals",
            "%+#1",
        ],
        capture_output=True,
        text=True,
        check=True,
    )
    value = proc.stdout.strip().splitlines()[0]
    return float(value)


def test_contrast_band_darkens_the_caption_baseline(
    tmp_path: Path,
    make_lavfi_clip_openh264,
) -> None:  # pragma: no cover - live-gated
    if not _signalstats_available():
        pytest.skip("ffmpeg build lacks the signalstats filter")
    src = make_lavfi_clip_openh264(f"color=c=white:s=1080x1920:r=30:d={CLIP_SECONDS}", audio=True)
    default_mp4 = _render(src, _write_ass(tmp_path / "d.ass", DEFAULT_PRESET), tmp_path / "d.mp4")
    band_mp4 = _render(src, _write_ass(tmp_path / "b.ass", CONTRAST_BAND_BS3), tmp_path / "b.mp4")
    trans_mp4 = _render(
        src, _write_ass(tmp_path / "t.ass", CONTRAST_BAND_TRANSLUCENT), tmp_path / "t.mp4"
    )

    y_default = _mid_frame_yavg(default_mp4)
    y_band = _mid_frame_yavg(band_mp4)
    y_trans = _mid_frame_yavg(trans_mp4)
    print(
        f"[A6 band gate] YAVG default={y_default:.1f} opaque={y_band:.1f} translucent={y_trans:.1f}"
    )

    # Opaque box validated UNCONDITIONALLY (bs=3 has no version dependency).
    assert y_band < y_default - OPAQUE_LUMA_DROP
    # Translucent box darkens less, but always positively (degrade-safe to opaque).
    assert y_trans <= y_default - TRANSLUCENT_MIN_LUMA_DROP


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
