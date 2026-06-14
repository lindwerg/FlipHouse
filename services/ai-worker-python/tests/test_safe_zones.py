"""Unit tests for the safe-zone invariant validator (docs/01 §2).

Zones are ``(x0, x1, y0, y1)`` rectangles in the 1080x1920 vertical frame.
Invariant: ``caption_band`` must sit inside ``content_safe`` and must never
overlap the reserved ``banner`` strip (1180 + 420 = 1600 <= 1640).
"""

import pytest

from fliphouse_worker.safe_zones import validate_safe_zones

CONTENT_SAFE = (0, 1080, 0, 1920)
CAPTION_BAND = (0, 1080, 1180, 1600)
BANNER = (0, 1080, 1640, 1920)


def test_caption_band_within_content_safe():
    # Arrange / Act
    result = validate_safe_zones(
        content_safe=CONTENT_SAFE,
        caption_band=CAPTION_BAND,
        banner=BANNER,
    )

    # Assert
    assert result is True


def test_caption_band_overlapping_banner_is_rejected():
    # caption_band extends to y1=1700, crossing into the banner strip (y0=1640)
    overlapping_band = (0, 1080, 1180, 1700)

    with pytest.raises(ValueError):
        validate_safe_zones(
            content_safe=CONTENT_SAFE,
            caption_band=overlapping_band,
            banner=BANNER,
        )


def test_caption_band_outside_content_safe_is_rejected():
    # content_safe is narrower than the caption band on the x axis
    narrow_content_safe = (100, 980, 0, 1920)

    with pytest.raises(ValueError):
        validate_safe_zones(
            content_safe=narrow_content_safe,
            caption_band=CAPTION_BAND,
            banner=BANNER,
        )
