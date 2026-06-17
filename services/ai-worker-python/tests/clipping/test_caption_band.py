"""caption_band — pure temporal-stability detector + fail-open clip wrapper."""

import numpy as np

from fliphouse_worker.clipping.caption_band import (
    CaptionBand,
    detect_caption_band,
    detect_clip_caption_band,
)


def _stack(n_frames: int, n_rows: int) -> np.ndarray:
    """Low constant background edge-energy (stable, unremarkable)."""
    return np.ones((n_frames, n_rows), dtype=np.float64)


# ── detect_caption_band (pure) ─────────────────────────────────────────────


def test_stable_high_band_in_lower_third_is_detected():
    arr = _stack(8, 100)
    arr[:, 90:95] = 10.0  # constant over time (stable) + high edge energy
    band = detect_caption_band(arr)
    assert isinstance(band, CaptionBand)
    assert (band.y_top, band.y_bottom) == (90, 94)
    assert 0.0 <= band.confidence <= 1.0


def test_busy_high_variance_band_is_rejected():
    arr = _stack(8, 100)
    # high mean but unstable over time (flickers 20/0) → not a caption
    arr[0::2, 90:95] = 20.0
    arr[1::2, 90:95] = 0.0
    assert detect_caption_band(arr) is None


def test_uniform_region_has_no_caption():
    assert detect_caption_band(_stack(8, 100)) is None


def test_band_wider_than_max_frac_is_rejected():
    arr = _stack(8, 100)
    # a stable bright block filling ~2/3 of the lower region is a graphic, not a
    # thin caption → rejected by the MAX_BAND_FRAC guard
    arr[:, 70:90] = 50.0
    assert detect_caption_band(arr) is None


def test_below_min_frames_returns_none():
    arr = _stack(3, 100)
    arr[:, 90:95] = 10.0
    assert detect_caption_band(arr) is None


def test_non_2d_input_returns_none():
    assert detect_caption_band(np.ones(50, dtype=np.float64)) is None


def test_empty_rows_returns_none():
    assert detect_caption_band(np.zeros((8, 0), dtype=np.float64)) is None


# ── detect_clip_caption_band (fail-open wrapper) ───────────────────────────


def test_clip_wrapper_returns_band_from_producer():
    arr = _stack(8, 100)
    arr[:, 90:95] = 10.0
    band = detect_clip_caption_band("s.mp4", 0.0, 5.0, _row_energy_fn=lambda *a: arr)
    assert isinstance(band, CaptionBand)


def test_clip_wrapper_fails_open_on_producer_error():
    def boom(*_a):
        raise RuntimeError("cv2 exploded")

    assert detect_clip_caption_band("s.mp4", 0.0, 5.0, _row_energy_fn=boom) is None


def test_caption_band_to_dict_round_trips():
    assert CaptionBand(90, 94, 0.5).to_dict() == {
        "y_top": 90,
        "y_bottom": 94,
        "confidence": 0.5,
    }
