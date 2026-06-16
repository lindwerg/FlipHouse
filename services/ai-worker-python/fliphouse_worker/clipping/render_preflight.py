"""Startup codec preflight for the H.264/AAC delivery render (P2-2.4 render).

The delivery clips are LGPL-clean H.264 via ``libopenh264`` (NOT x264/x265, which
need ``--enable-gpl``). The Railway runtime is an LGPL ffmpeg build; if it lacks
``libopenh264`` the render leg is permanently inert. This turns that into a loud,
fail-fast boot error. Mirrors ``preflight.assert_clip_codecs``; exported for a
job-runner / boot entrypoint to call, NOT auto-wired (importing this module on a
GPL dev box that has only libx264 must never raise).

``_probe_render_encoders`` is the only impure boundary (mirrors the cutter seam).
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

logger = logging.getLogger(__name__)

REQUIRED_DELIVERY_ENCODERS = ("libopenh264", "aac")


def _probe_render_encoders() -> str:  # pragma: no cover - thin ffmpeg boundary, live-gated
    """Return ``ffmpeg -encoders`` output (the only ffmpeg call here)."""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def assert_render_codecs(*, _run_fn: Callable[[], str] = _probe_render_encoders) -> None:
    """Assert the delivery encoders are present, else log CRITICAL and raise.

    ``_run_fn`` is the test seam. Call once at worker boot, alongside
    ``assert_clip_codecs``.
    """
    listing = _run_fn()
    missing = [enc for enc in REQUIRED_DELIVERY_ENCODERS if enc not in listing]
    if missing:
        logger.critical(
            "ffmpeg build is missing required delivery encoders %s — the vertical "
            "render leg will be 100%% inert",
            missing,
        )
        raise RuntimeError(f"ffmpeg missing required delivery encoders: {missing}")
