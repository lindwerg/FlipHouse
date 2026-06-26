"""P3-A3 LIVE gate — the active-word pop must be (1) cheap enough per frame and
(2) actually rasterized, on a REAL libass+ffmpeg render.

Kinetic captions are free by NUMBER of encodes (the pop is pure ASS overrides folded
into the single libopenh264 pass — SPD-1) but NOT free by wall-time: libass re-rasterizes
the animated ``\\t`` every output frame. A byte-diff of the ``.ass`` cannot catch a
wall-time blow-up or a pop that silently no-ops, so this gate renders the pop=True and
pop=False clips through the production argv and compares.

It is OPT-IN: skipped unless ``FLIPHOUSE_LIVE_CAPTIONS=1`` and ffmpeg/ffprobe (with
libopenh264 + libass) are on PATH. CI never sets the flag, so it is COLLECTED+SKIPPED —
it never reports a green pass and never enters the source-scoped 100 % coverage gate
(coverage measures ``fliphouse_worker`` only; this file runs all rendering inside skipped
bodies). Run locally with:

    FLIPHOUSE_LIVE_CAPTIONS=1 pytest -m live tests/captioning/test_pop_live_golden.py
"""

from __future__ import annotations

import dataclasses
import os
import re
import subprocess
import time
from pathlib import Path

import pytest

from fliphouse_worker.captioning.ass import DEFAULT_PRESET, build_caption_ass, group_caption_lines
from fliphouse_worker.captioning.segments import CaptionWord
from fliphouse_worker.clipping import render
from fliphouse_worker.clipping.crop_geometry import CROP_MODE, CropBox
from fliphouse_worker.video_asserts import assert_duration, probe_duration_seconds

pytestmark = [
    pytest.mark.live,
    pytest.mark.skipif(
        os.environ.get("FLIPHOUSE_LIVE_CAPTIONS") != "1",
        reason="set FLIPHOUSE_LIVE_CAPTIONS=1 to run the captioned-clip wall-time/SSIM pop gate",
    ),
]

CLIP_SECONDS = 3.0
POP_WALL_BUDGET_FACTOR = 1.50  # pop may cost more per frame, but not runaway
MIN_MEAN_SSIM = 0.90  # the two clips are mostly identical (only the active word scales)
MAX_MEAN_SSIM = 0.9995  # strictly < 1.0 → the pop ACTUALLY rasterized a visible delta
DURATION_TOL_S = 0.05


def _words() -> tuple[CaptionWord, ...]:
    # A few short words spanning [0, CLIP_SECONDS) plus one long token so the
    # autoscale-compose branch is exercised too.
    spans = [
        ("деньги", 0.0, 0.5),
        ("на", 0.5, 0.9),
        ("входе", 0.9, 1.5),
        ("предприниматель", 1.5, 2.3),
        ("сразу", 2.3, CLIP_SECONDS),
    ]
    return tuple(CaptionWord(text=t, start=s, end=e) for t, s, e in spans)


def _write_ass(path: Path, pop: bool) -> Path:  # pragma: no cover - live-gated
    preset = dataclasses.replace(DEFAULT_PRESET, pop=pop)
    lines = group_caption_lines(_words())
    path.write_text(build_caption_ass(lines, preset=preset), encoding="utf-8")
    return path


def _render(src: Path, ass_path: Path, out: Path) -> float:  # pragma: no cover - live-gated
    box = CropBox(x=0, y=0, w=1080, h=1920, mode=CROP_MODE)
    argv = render._build_render_argv(
        str(src), 0.0, CLIP_SECONDS, box, out, 1080, 1920, render.TARGET_BITRATE, ass_path
    )
    started = time.perf_counter()
    subprocess.run(argv, check=True, capture_output=True)
    return time.perf_counter() - started


def _mean_ssim(a: Path, b: Path) -> float:  # pragma: no cover - live-gated
    proc = subprocess.run(
        ["ffmpeg", "-hide_banner", "-i", str(a), "-i", str(b), "-lavfi", "ssim", "-f", "null", "-"],
        capture_output=True,
        text=True,
        check=True,
    )
    match = re.search(r"All:([0-9.]+)", proc.stderr)
    assert match, f"no SSIM in ffmpeg output:\n{proc.stderr}"
    return float(match.group(1))


def test_pop_render_is_within_walltime_budget_and_actually_rasterizes(
    tmp_path: Path,
    make_lavfi_clip_openh264,
) -> None:  # pragma: no cover - live-gated
    src = make_lavfi_clip_openh264(
        f"testsrc2=size=1080x1920:rate=30:duration={CLIP_SECONDS}", audio=True
    )
    base_mp4 = _render(src, _write_ass(tmp_path / "base.ass", pop=False), tmp_path / "base.mp4")
    pop_mp4 = _render(src, _write_ass(tmp_path / "pop.ass", pop=True), tmp_path / "pop.mp4")

    # (1) wall-time: best-of-2 each so a noisy run does not flake; pop stays bounded.
    base_wall = min(
        _render(src, tmp_path / "base.ass", tmp_path / "base2.mp4"),
        _render(src, tmp_path / "base.ass", tmp_path / "base3.mp4"),
    )
    pop_wall = min(
        _render(src, tmp_path / "pop.ass", tmp_path / "pop2.mp4"),
        _render(src, tmp_path / "pop.ass", tmp_path / "pop3.mp4"),
    )
    print(f"[A3 pop gate] base_wall={base_wall:.3f}s pop_wall={pop_wall:.3f}s")
    assert pop_wall <= base_wall * POP_WALL_BUDGET_FACTOR
    assert pop_wall <= CLIP_SECONDS * render.RENDER_REALTIME_FACTOR

    # (2) same duration, and the pop is present yet not corrupting frames.
    assert_duration(pop_mp4, probe_duration_seconds(base_mp4), DURATION_TOL_S)
    mean_ssim = _mean_ssim(pop_mp4, base_mp4)
    print(f"[A3 pop gate] mean_ssim(pop, base)={mean_ssim:.5f}")
    assert MIN_MEAN_SSIM <= mean_ssim < MAX_MEAN_SSIM
