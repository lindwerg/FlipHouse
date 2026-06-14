"""Safe-zone invariant validator for the vertical render frame (docs/01 §2).

A zone is an axis-aligned rectangle ``(x0, x1, y0, y1)`` in the 1080x1920 frame,
where ``x0 < x1`` is the horizontal span and ``y0 < y1`` the vertical span (origin
top-left). The caption band carries burned-in subtitles; the banner strip is the
region reserved for the advertiser overlay inserted in P4.

The invariant the pipeline must preserve:
    caption_band ⊂ content_safe  AND  caption_band ∩ banner = ∅

Keeping captions inside the content-safe region and disjoint from the banner is
what guarantees "zero caption pixels in the banner strip" for later phases.
"""

# A zone rectangle: (x0, x1, y0, y1).
Zone = tuple[int, int, int, int]


def _contains(outer: Zone, inner: Zone) -> bool:
    """Return True when ``inner`` lies fully within ``outer`` (inclusive edges)."""
    ox0, ox1, oy0, oy1 = outer
    ix0, ix1, iy0, iy1 = inner
    return ox0 <= ix0 and ix1 <= ox1 and oy0 <= iy0 and iy1 <= oy1


def _overlaps(a: Zone, b: Zone) -> bool:
    """Return True when AABB rectangles ``a`` and ``b`` share interior area."""
    ax0, ax1, ay0, ay1 = a
    bx0, bx1, by0, by1 = b
    x_overlap = ax0 < bx1 and bx0 < ax1
    y_overlap = ay0 < by1 and by0 < ay1
    return x_overlap and y_overlap


def validate_safe_zones(
    content_safe: Zone,
    caption_band: Zone,
    banner: Zone,
) -> bool:
    """Validate the caption safe-zone invariant.

    Returns ``True`` when ``caption_band`` is contained in ``content_safe`` and is
    disjoint from ``banner``. Raises ``ValueError`` otherwise.
    """
    if not _contains(content_safe, caption_band):
        raise ValueError("caption_band must lie within content_safe")
    if _overlaps(caption_band, banner):
        raise ValueError("caption_band must not overlap the banner strip")
    return True
