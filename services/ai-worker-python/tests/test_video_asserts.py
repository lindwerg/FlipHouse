"""Tests for the golden-file video assertion harness (P0.7).

These prove the *assertion contract* P1/P2/P3 will use to verify the render is
correct (vertical 9:16, banner actually on screen, captions present), not merely
that a job finished without error.
"""

from collections.abc import Callable
from pathlib import Path

import pytest

from fliphouse_worker.video_asserts import (
    assert_duration,
    frame_phash,
    probe_dimensions,
    probe_duration_seconds,
    probe_fps,
    region_has_content,
)

# Banner strip in the 1080x1920 frame: (x0, x1, y0, y1).
BANNER = (0, 1080, 1640, 1920)


def test_assert_dimensions_matches_vertical_1080x1920(make_test_clip: Callable[[], Path]):
    assert probe_dimensions(make_test_clip()) == (1080, 1920)


def test_assert_duration_within_tolerance(make_test_clip: Callable[[], Path]):
    # Must not raise for a ~1.0s clip within tolerance.
    assert_duration(make_test_clip(), expected=1.0, tol=0.05)


def test_assert_fps_is_24(make_test_clip: Callable[[], Path]):
    assert probe_fps(make_test_clip()) == 24


def test_probe_duration_seconds_reads_container_duration(make_test_clip: Callable[[], Path]):
    # The ~1.0s golden clip — the PAYG billable quantity, in seconds.
    assert probe_duration_seconds(make_test_clip()) == pytest.approx(1.0, abs=0.05)


def test_frame_phash_is_stable_across_two_extractions(make_test_clip: Callable[[], Path]):
    clip = make_test_clip()
    assert frame_phash(clip, t=0.5) - frame_phash(clip, t=0.5) == 0


def test_detects_overlay_presence_via_pixel_region(make_lavfi_clip: Callable[..., Path]):
    clean = make_lavfi_clip("color=c=black:s=1080x1920:rate=24:duration=1")
    overlay = make_lavfi_clip(
        "color=c=black:s=1080x1920:rate=24:duration=1",
        vf="drawbox=x=0:y=1640:w=1080:h=280:color=white:t=fill",
    )
    assert region_has_content(overlay, region=BANNER) is True
    assert region_has_content(clean, region=BANNER) is False


def test_assert_duration_raises_when_out_of_tolerance(make_test_clip: Callable[[], Path]):
    with pytest.raises(AssertionError):
        assert_duration(make_test_clip(), expected=5.0, tol=0.05)
