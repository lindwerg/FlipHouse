"""Shared pytest fixtures — deterministic FFmpeg-generated test clips.

P0 has no render pipeline, so the golden-file assertion harness is exercised
against tiny clips synthesised via FFmpeg `lavfi` sources.
"""

import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest


def _ffmpeg(args: list[str]) -> None:
    subprocess.run(["ffmpeg", "-y", "-v", "error", *args], check=True)


@pytest.fixture
def make_lavfi_clip(tmp_path: Path) -> Callable[..., Path]:
    """Factory: build a 1080x1920@24 clip from any lavfi source (+ optional -vf)."""
    counter = {"n": 0}

    def _make(source: str, vf: str | None = None) -> Path:
        counter["n"] += 1
        out = tmp_path / f"clip_{counter['n']}.mp4"
        args = ["-f", "lavfi", "-i", source]
        if vf is not None:
            args += ["-vf", vf]
        args += [str(out)]
        _ffmpeg(args)
        return out

    return _make


@pytest.fixture
def make_test_clip(make_lavfi_clip: Callable[..., Path]) -> Callable[[], Path]:
    """Factory for the canonical vertical test clip (testsrc, 1080x1920, 24fps, 1s)."""

    def _make() -> Path:
        return make_lavfi_clip("testsrc=size=1080x1920:rate=24:duration=1")

    return _make
