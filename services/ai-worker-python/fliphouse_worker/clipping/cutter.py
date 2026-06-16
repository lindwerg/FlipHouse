"""Pre-cut a short WebM clip for Stage B native A/V scoring (P2-S6).

Each surviving Stage-A recall candidate is re-encoded to a tiny VP9/Opus WebM
(``≤~50s``, capped at ``-fs 9M``) and handed to the multimodal ``ClipScorer`` as
inline base64 ``video_url``. Re-encoding (not stream-copy) is deliberate: the
orchestrator owns the timecodes, so a keyframe-snapped copy would corrupt clip
bounds, and stream-copy cannot cap the byte budget. VP9 + Opus are LGPL-clean
(no ``--enable-gpl``, unlike x264/x265), and ``video/webm`` is already in the
adapter's ``SUPPORTED_VIDEO_MIMES``.

``_run_clip_ffmpeg`` is the ONLY impure boundary (mirrors
``dsp/audio_energy.py::_run_audio_ffmpeg``): a single ffmpeg pipe to stdout,
mocked in tests by patching ``subprocess.run`` or injecting ``_run_fn``.
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

from ..llm.content_parts import MAX_INLINE_VIDEO_BYTES

logger = logging.getLogger(__name__)

CLIP_VIDEO_MIME = "video/webm"

# Encoder knobs — small enough for Gemini's eyes, tiny on the wire, fast on CPU.
SCALE = "scale=-2:480"  # cap height at 480p, keep aspect (even width via -2)
FPS = 15  # 15 fps preserves motion cues at a quarter of 60 fps bytes
CRF = 34  # VP9 constant-quality; higher = smaller. 34 ≈ 2-9 MB for 50s @480p15
AUDIO_BITRATE = "32k"  # Opus stays intelligible (speech) well below this

# Hard size cap handed to ffmpeg's ``-fs`` (output is truncated, never oversize).
FS_LIMIT = "9M"
# Above this fraction of the cap, the clip was probably ``-fs``-truncated mid-
# stream (its tail/punchline may be missing) — a signal worth a WARNING.
FS_NEAR_LIMIT_RATIO = 0.97

# The model-side inline cap (base64 +33% still clears OpenRouter's 100 MB limit).
MAX_CLIP_BYTES = MAX_INLINE_VIDEO_BYTES

_SUFFIX_FACTORS = {"K": 1024, "M": 1024**2, "G": 1024**3}


def _fs_bytes(spec: str) -> int:
    """Parse an ffmpeg size spec like ``9M`` into bytes (K/M/G = 1024-based)."""
    factor = _SUFFIX_FACTORS.get(spec[-1].upper())
    if factor is None:
        return int(spec)
    return int(float(spec[:-1]) * factor)


# The real ffmpeg path can only exceed MAX_CLIP_BYTES if ``-fs`` is misconfigured
# above the inline cap — this invariant locks that condition. An explicit raise
# (not ``assert``) so ``python -O`` can never strip this deployment guard.
if _fs_bytes(FS_LIMIT) > MAX_CLIP_BYTES:  # pragma: no cover - unreachable by design
    raise AssertionError(
        f"FS_LIMIT {FS_LIMIT} ({_fs_bytes(FS_LIMIT)} bytes) exceeds the inline cap "
        f"MAX_CLIP_BYTES ({MAX_CLIP_BYTES}) — lower FS_LIMIT or raise the cap"
    )


class ClipTooLargeError(ValueError):
    """Encoded clip still exceeds the inline cap (a misconfiguration guard)."""


def _run_clip_ffmpeg(src: str, start: float, end: float) -> bytes:
    """Re-encode ``src[start:end]`` to a VP9/Opus WebM on stdout (only ffmpeg call)."""
    return subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-ss",
            f"{start}",
            "-i",
            src,
            "-t",
            f"{end - start}",
            "-vf",
            f"{SCALE},fps={FPS}",
            "-c:v",
            "libvpx-vp9",
            "-b:v",
            "0",
            "-crf",
            str(CRF),
            "-deadline",
            "good",
            "-cpu-used",
            "5",
            "-row-mt",
            "1",
            "-c:a",
            "libopus",
            "-b:a",
            AUDIO_BITRATE,
            "-fs",
            FS_LIMIT,
            "-f",
            "webm",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


def cut_clip(
    src: str,
    start: float,
    end: float,
    *,
    _run_fn: Callable[[str, float, float], bytes] = _run_clip_ffmpeg,
) -> bytes:
    """Cut ``src`` to a small WebM clip's bytes. ``_run_fn`` is the test seam.

    Fails closed: a non-positive span raises before the seam runs; an over-cap
    payload raises :class:`ClipTooLargeError`; a likely ``-fs``-truncated clip is
    returned but logged (it is scored on a partial view).
    """
    if end <= start:
        raise ValueError(f"clip span must be positive, got [{start}, {end}]")
    out = _run_fn(src, start, end)
    if len(out) > MAX_CLIP_BYTES:
        raise ClipTooLargeError(f"clip is {len(out)} bytes, over cap {MAX_CLIP_BYTES}")
    if len(out) >= FS_NEAR_LIMIT_RATIO * _fs_bytes(FS_LIMIT):
        logger.warning(
            "clip [%s, %s] near -fs limit (%d bytes) — likely -fs-truncated; A/V scoring "
            "will attempt it but may fall back to text if the container is corrupt",
            start,
            end,
            len(out),
        )
    return out
