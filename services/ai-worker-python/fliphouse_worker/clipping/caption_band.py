"""Source burned-in caption detection (P2 reframe step 5).

Some source videos already carry burned-in subtitles in the lower third. Our own
captions (P3) must sit ABOVE that band so the two don't overlap. This module
detects the source band and RECORDS it in the manifest — it never alters the crop
geometry (which keeps full height, so a caption is never vertically lost) and it
NEVER blocks a clip: every uncertain or failed detection returns ``None``
(fail-open) and rendering proceeds exactly as before.

The PURE core (:func:`detect_caption_band`) consumes an already-built row-energy
stack ``(n_frames, n_rows)`` and does only temporal statistics on plain numpy. A
caption row is a high-edge-energy row that is STABLE over time (low temporal
variance is the key discriminator against a busy moving background). The cv2
decode + Sobel that produces the stack lives in a ``# pragma: no cover`` boundary.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

import numpy as np

CAPTION_SEARCH_BOTTOM_FRAC = 0.30  # captions live in the lower third — search only there
CAPTION_K_STD = 2.0  # a caption row's edge-energy must clear mean + k·std
CAPTION_MAX_BAND_FRAC = 0.40  # a "band" filling >40% of the search region is not a caption
CAPTION_MIN_FRAMES = 4  # fewer sampled frames than this → too little signal → None
_EPS = 1e-9


@dataclass(frozen=True)
class CaptionBand:
    """A detected source-caption band in source pixels (top-left origin)."""

    y_top: int
    y_bottom: int
    confidence: float

    def to_dict(self) -> dict[str, object]:
        return {"y_top": self.y_top, "y_bottom": self.y_bottom, "confidence": self.confidence}


# A clip-level detector: (src, start, end) → CaptionBand | None (fail-open).
CaptionBandFn = Callable[[str, float, float], "CaptionBand | None"]
# Producer of the row-energy stack for a clip window (the impure cv2 boundary).
RowEnergyFn = Callable[[str, float, float], np.ndarray]


def detect_caption_band(row_energy_stack: np.ndarray) -> CaptionBand | None:
    """PURE. ``(n_frames, n_rows)`` row-edge-energy stack → a stable lower band or None.

    A caption row clears ``mean + CAPTION_K_STD·std`` of the search region's
    per-row temporal means AND has below-median temporal variance (text is stable;
    moving background is not). Contiguous caption rows form the band; any
    uncertainty (wrong shape, too few frames, no qualifying row, band wider than
    ``CAPTION_MAX_BAND_FRAC`` of the search region) returns ``None``.
    """
    arr = np.asarray(row_energy_stack, dtype=np.float64)
    if arr.ndim != 2 or arr.shape[0] < CAPTION_MIN_FRAMES:
        return None
    n_rows = arr.shape[1]
    search_start = int(round(n_rows * (1.0 - CAPTION_SEARCH_BOTTOM_FRAC)))
    region = arr[:, search_start:]
    if region.shape[1] == 0:
        return None

    row_mean = region.mean(axis=0)
    row_std = region.std(axis=0)
    # Threshold off the darkest (background-floor) row, not the region mean — a wide
    # bright band must not raise its own bar above itself (keeps the MAX_BAND_FRAC
    # guard reachable: a band filling most of the lower region is a graphic, not a
    # caption).
    mean_thresh = float(row_mean.min() + CAPTION_K_STD * row_mean.std())
    std_thresh = float(np.median(row_std))
    caption_like = (row_mean > mean_thresh) & (row_std <= std_thresh)
    rows = np.flatnonzero(caption_like)
    if rows.size == 0:
        return None

    run = max(np.split(rows, np.flatnonzero(np.diff(rows) != 1) + 1), key=len)
    if run.size / region.shape[1] > CAPTION_MAX_BAND_FRAC:
        return None

    band_mean = float(row_mean[run].mean())
    overall = float(row_mean.mean())
    confidence = round(max(0.0, min(1.0, (band_mean - overall) / (band_mean + _EPS))), 4)
    return CaptionBand(
        y_top=search_start + int(run[0]),
        y_bottom=search_start + int(run[-1]),
        confidence=confidence,
    )


def _row_energy_stack_cv2(
    src: str, start: float, end: float
) -> np.ndarray:  # pragma: no cover - live cv2/Sobel boundary
    """Decode sampled frames of ``src[start:end]`` → per-row Sobel edge energy stack."""
    import cv2  # noqa: PLC0415 — lazy: only the live caption path needs OpenCV

    cap = cv2.VideoCapture(src)
    rows: list[np.ndarray] = []
    try:
        step = 1.0 / 2.0
        t = start
        while t < end:
            cap.set(cv2.CAP_PROP_POS_MSEC, t * 1000.0)
            ok, frame = cap.read()
            if not ok:
                break
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            sobel = np.abs(cv2.Sobel(gray, cv2.CV_64F, 1, 0, ksize=3))
            rows.append(sobel.sum(axis=1))
            t += step
    finally:
        cap.release()
    return np.asarray(rows, dtype=np.float64)


def detect_clip_caption_band(
    src: str,
    start: float,
    end: float,
    *,
    _row_energy_fn: RowEnergyFn = _row_energy_stack_cv2,
) -> CaptionBand | None:
    """Fail-open clip-level detector: any producer error → ``None`` (never blocks a clip)."""
    try:
        stack = _row_energy_fn(src, start, end)
    except Exception:  # noqa: BLE001 — fail-open by design: detection must never block render
        return None
    return detect_caption_band(stack)
