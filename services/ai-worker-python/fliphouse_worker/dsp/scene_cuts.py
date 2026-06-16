"""Stage 0 video DSP (P2-S5): shot-boundary / scene-cut detection.

Uses ffmpeg's native ``scdet`` filter on a 320-wide downscaled stream — no
PySceneDetect / OpenCV (a ~60 MB wheel needing libGL, hostile to the slim
Railway image and to the 100 % coverage gate, which has no clean frame seam for
cv2). scdet is a core libavfilter component: LGPL-safe, no x264.

ffmpeg ``metadata=print:file=-`` emits, per detected frame, a block of
``lavfi.scd.score=…`` / ``lavfi.scd.time=…`` lines on stdout (verified on
ffmpeg 8.1). The filter pre-thresholds at ``t``; we keep it permissive and apply
a second Python-side floor so the parser can be unit-tested across score ranges.
Dense cuts mark high-energy, editable moments — Stage A up-weights candidates
whose hook sits near a cut.
"""

from __future__ import annotations

import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass

SCDET_THRESHOLD = 5  # permissive filter-side threshold; real cuts separated by the floor below
CUT_SCORE_FLOOR = 14.0  # Python-side floor: scores >= this are treated as genuine cuts
DOWNSCALE_W = 320  # scene detection needs no resolution; downscale for CPU speed + determinism

_SCORE_RE = re.compile(r"lavfi\.scd\.score=([0-9.]+)")
_TIME_RE = re.compile(r"lavfi\.scd\.time=([0-9.]+)")


@dataclass(frozen=True)
class SceneCut:
    """A detected shot boundary."""

    time_s: float
    score: float


def _run_video_ffmpeg(src: str) -> str:
    """Run scdet on ``src``; return the metadata stdout text (the only ffmpeg call)."""
    return subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-loglevel",
            "error",
            "-i",
            src,
            "-vf",
            f"scale={DOWNSCALE_W}:-2,scdet=s=1:t={SCDET_THRESHOLD},metadata=print:file=-",
            "-an",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
    ).stdout.decode("utf-8", errors="replace")


def parse_cuts(output: str, score_floor: float = CUT_SCORE_FLOOR) -> tuple[SceneCut, ...]:
    """Parse scdet metadata text → scene cuts at or above ``score_floor``.

    A block emits ``score`` before ``time``; a ``time`` line with no pending
    score (malformed/partial block) is skipped rather than crashing.
    """
    cuts: list[SceneCut] = []
    pending_score: float | None = None
    for line in output.splitlines():
        score_match = _SCORE_RE.search(line)
        if score_match:
            pending_score = float(score_match.group(1))
            continue
        time_match = _TIME_RE.search(line)
        if time_match and pending_score is not None:
            if pending_score >= score_floor:
                cuts.append(SceneCut(time_s=float(time_match.group(1)), score=pending_score))
            pending_score = None
    return tuple(cuts)


def extract_scene_cuts(
    src: str, *, _run_fn: Callable[[str], str] = _run_video_ffmpeg
) -> tuple[SceneCut, ...]:
    """Detect scene cuts in ``src``. ``_run_fn`` is the test seam."""
    return parse_cuts(_run_fn(src))
