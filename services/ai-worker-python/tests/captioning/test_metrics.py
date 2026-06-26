"""P3-A3 — real glyph-advance widths from the vendored caption font (hmtx)."""

from __future__ import annotations

from fliphouse_worker.captioning.metrics import (
    FALLBACK_ADVANCE_EM,
    _advance_table_em,
    text_width_em,
)


def test_empty_string_has_zero_width() -> None:
    assert text_width_em("") == 0.0


def test_cyrillic_is_wider_than_the_latin_heuristic() -> None:
    # The whole point of A3 using real metrics: Cyrillic advances exceed the Latin
    # 0.62·em the legacy estimate assumes, so a true measure is strictly wider.
    russian_mean = text_width_em("больше шума") / len("больше шума")
    assert russian_mean > 0.62


def test_known_phrase_width_matches_measured_font() -> None:
    # Pinned against the vendored Montserrat-ExtraBold hmtx (unitsPerEm=1000).
    assert round(text_width_em("больше шума"), 3) == 7.633


def test_missing_glyph_falls_back_to_conservative_advance() -> None:
    # A codepoint absent from the cmap must use the conservative fallback so an
    # unknown glyph can only ever UNDER-pop (never clip). U+E000 is a private-use
    # codepoint not present in the font.
    private_use = chr(0xE000)
    assert ord(private_use) not in _advance_table_em()
    assert text_width_em(private_use) == FALLBACK_ADVANCE_EM


def test_advance_table_is_cached_singleton() -> None:
    assert _advance_table_em() is _advance_table_em()


def test_missing_font_file_falls_back_to_conservative_widths(monkeypatch, tmp_path) -> None:
    # A broken/incomplete install (font absent) must fail SOFT: every codepoint uses
    # the conservative fallback so pop captions under-pop rather than crashing.
    from fliphouse_worker.captioning import metrics

    metrics._advance_table_em.cache_clear()
    monkeypatch.setattr(metrics, "_FONT_PATH", tmp_path / "does-not-exist.ttf")
    try:
        assert metrics._advance_table_em() == {}
        assert metrics.text_width_em("ab") == 2 * FALLBACK_ADVANCE_EM
    finally:
        metrics._advance_table_em.cache_clear()  # restore the real table for other tests
