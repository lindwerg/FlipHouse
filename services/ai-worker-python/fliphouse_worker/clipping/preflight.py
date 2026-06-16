"""Startup codec preflight for the WebM clipper (P2-S6).

The Railway runtime image is an LGPL ffmpeg build; if it lacks ``libvpx-vp9`` or
``libopus`` the whole A/V path degrades to 100% text-only fallback SILENTLY. This
turns that into a loud, fail-fast startup error instead of a permanently inert
feature. It is exported for a job-runner / boot entrypoint to call (no worker
entrypoint module exists in S6 yet), not auto-wired here.

``_probe_encoders`` is the only impure boundary (mirrors the cutter seam).
"""

from __future__ import annotations

import logging
import subprocess
from collections.abc import Callable

logger = logging.getLogger(__name__)

REQUIRED_ENCODERS = ("libvpx-vp9", "libopus")


def _probe_encoders() -> str:
    """Return ``ffmpeg -encoders`` output (the only ffmpeg call here)."""
    return subprocess.run(
        ["ffmpeg", "-hide_banner", "-encoders"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def assert_clip_codecs(*, _run_fn: Callable[[], str] = _probe_encoders) -> None:
    """Assert the WebM clipper's encoders are present, else log CRITICAL and raise.

    ``_run_fn`` is the test seam. Call this once at worker boot.
    """
    listing = _run_fn()
    missing = [enc for enc in REQUIRED_ENCODERS if enc not in listing]
    if missing:
        logger.critical(
            "ffmpeg build is missing required clip encoders %s — the A/V clipping "
            "path will be 100%% inert (silent text-only fallback)",
            missing,
        )
        raise RuntimeError(f"ffmpeg missing required encoders: {missing}")
