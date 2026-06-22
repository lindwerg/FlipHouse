"""Golden-file video assertion harness.

Deterministic checks on a rendered clip — dimensions, duration, frame rate,
perceptual frame hash, and presence of an opaque overlay in a pixel region.
These are the contract P1/P2/P3 use to prove the render is *correct*, not just
that the pipeline ran. Thin wrappers over ``ffprobe``/``ffmpeg`` + ``PIL``.
"""

import json
import subprocess
import tempfile
from pathlib import Path

import imagehash
from PIL import Image, ImageStat

# A pixel region: (x0, x1, y0, y1) in the frame's coordinate space.
Region = tuple[int, int, int, int]

# Mean luminance (0-255) above which a region counts as holding opaque content.
_CONTENT_LUMA_THRESHOLD = 128.0


def _ffprobe_stream(path: Path) -> dict:
    """Return the first video stream's ffprobe metadata as a dict."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height,r_frame_rate,codec_name,pix_fmt:format=duration",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    data = json.loads(out.stdout)
    stream = data["streams"][0]
    stream["duration"] = float(data["format"]["duration"])
    return stream


def probe_dimensions(path: Path) -> tuple[int, int]:
    """Return ``(width, height)`` of the clip's video stream."""
    stream = _ffprobe_stream(path)
    return int(stream["width"]), int(stream["height"])


def probe_duration_seconds(path: Path) -> float:
    """Return the source container's duration in seconds (the PAYG billable quantity)."""
    return _ffprobe_stream(path)["duration"]


def probe_fps(path: Path) -> int:
    """Return the integer frame rate parsed from ``r_frame_rate`` (e.g. ``24/1``)."""
    num, den = _ffprobe_stream(path)["r_frame_rate"].split("/")
    return round(int(num) / int(den))


def probe_video_codec(path: Path) -> str:
    """Return the video codec name (e.g. ``h264``)."""
    return _ffprobe_stream(path)["codec_name"]


def probe_pixel_format(path: Path) -> str:
    """Return the pixel format (e.g. ``yuv420p`` — the platform-compatible profile)."""
    return _ffprobe_stream(path)["pix_fmt"]


def has_audio(path: Path) -> bool:
    """Return True when the clip carries at least one audio stream."""
    out = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=index",
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    return len(json.loads(out.stdout).get("streams", [])) > 0


def assert_duration(path: Path, expected: float, tol: float) -> None:
    """Raise ``AssertionError`` when the clip duration is outside ``expected ± tol``."""
    actual = _ffprobe_stream(path)["duration"]
    if abs(actual - expected) > tol:
        raise AssertionError(f"duration {actual:.3f}s not within {expected}±{tol}s")


def _extract_frame(path: Path, t: float) -> Image.Image:
    """Extract a single RGB frame at timestamp ``t`` seconds via ffmpeg."""
    with tempfile.TemporaryDirectory() as tmp:
        frame = Path(tmp) / "frame.png"
        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-v",
                "error",
                "-ss",
                str(t),
                "-i",
                str(path),
                "-frames:v",
                "1",
                str(frame),
            ],
            check=True,
        )
        return Image.open(frame).convert("RGB")


def frame_phash(path: Path, t: float) -> imagehash.ImageHash:
    """Return the perceptual hash of the frame at ``t`` (deterministic for fixed ``t``)."""
    return imagehash.phash(_extract_frame(path, t))


def region_has_content(path: Path, region: Region) -> bool:
    """Return True when ``region`` holds a bright/opaque overlay (mean luma above threshold)."""
    x0, x1, y0, y1 = region
    crop = _extract_frame(path, t=0.0).crop((x0, y0, x1, y1)).convert("L")
    mean_luma = ImageStat.Stat(crop).mean[0]
    return mean_luma > _CONTENT_LUMA_THRESHOLD
