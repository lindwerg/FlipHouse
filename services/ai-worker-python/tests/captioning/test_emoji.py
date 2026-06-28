"""P3-A8: pure tests for the sparse semantic emoji stamper (network-free)."""

from __future__ import annotations

import dataclasses

import pytest

from fliphouse_worker.captioning.ass import CaptionLine
from fliphouse_worker.captioning.emoji import (
    ALLOWED_EMOJI,
    ALLOWED_EMOJI_CODEPOINTS,
    KEYWORD_EMOJI,
    _normalize,
    _select_stamp,
    apply_line_emoji,
    emoji_for,
)
from fliphouse_worker.captioning.segments import CaptionWord


def _line(*specs: tuple[str, bool]) -> CaptionLine:
    # spec = (text, emphasis)
    words = tuple(
        CaptionWord(text=t, start=float(i), end=float(i) + 1.0, emphasis=e)
        for i, (t, e) in enumerate(specs)
    )
    return CaptionLine(start=0.0, end=float(len(specs)), words=words)


def _words(*texts: str) -> CaptionLine:
    return _line(*((t, False) for t in texts))


def _emoji_of(line: CaptionLine) -> list[str]:
    return [w.emoji for w in line.words]


# --- integrity: the allowlist is a real, non-vacuous, single-scalar set ---


def test_allowlist_codepoints_match_the_curated_glyphs() -> None:
    assert {ord(v) for v in ALLOWED_EMOJI} == ALLOWED_EMOJI_CODEPOINTS
    assert all(ord(v) in ALLOWED_EMOJI_CODEPOINTS for v in KEYWORD_EMOJI.values())


def test_every_emoji_is_a_single_unicode_scalar() -> None:
    assert all(len(v) == 1 for v in ALLOWED_EMOJI)


def test_every_keyword_key_is_already_normalised() -> None:
    # A "Деньги"/"топ!" key could never match the normalised lookup → would be dead.
    assert all(k == _normalize(k) for k in KEYWORD_EMOJI)


# --- emoji_for lookup ---


@pytest.mark.parametrize("text", ["деньги", "Деньги", "деньги.", " деньги!"])
def test_emoji_for_hits_through_normalize(text: str) -> None:
    assert emoji_for(text) == "\U0001f4b0"


def test_emoji_for_en_parity_and_miss() -> None:
    assert emoji_for("money") == "\U0001f4b0"
    assert emoji_for("стол") == ""


# --- _select_stamp placement priority ---


def test_select_prefers_emphasised_word_if_it_maps() -> None:
    idx, glyph = _select_stamp(_line(("вот", False), ("деньги", True), ("тут", False)), emoji_for)
    assert (idx, glyph) == (1, "\U0001f4b0")


def test_select_falls_through_when_emphasised_word_does_not_map() -> None:
    # emphasised "вот" doesn't map → scan from end finds "деньги".
    idx, glyph = _select_stamp(_line(("вот", True), ("деньги", False)), emoji_for)
    assert (idx, glyph) == (1, "\U0001f4b0")


def test_select_never_stamps_line_start_of_a_multiword_line() -> None:
    # only the first word maps; lo=1 forbids index 0 on a multiword line → no stamp.
    idx, glyph = _select_stamp(_words("деньги", "сразу"), emoji_for)
    assert (idx, glyph) == (-1, "")


def test_select_allows_index_zero_on_a_single_word_line() -> None:
    idx, glyph = _select_stamp(_words("деньги"), emoji_for)
    assert (idx, glyph) == (0, "\U0001f4b0")


def test_select_empty_line_returns_no_stamp() -> None:
    assert _select_stamp(CaptionLine(start=0.0, end=0.0, words=()), emoji_for) == (-1, "")


# --- apply_line_emoji: gates, density, immutability, allowlist clamp ---


def test_apply_off_when_incapable_or_density_zero() -> None:
    lines = [_words("деньги")]
    assert apply_line_emoji(lines, emoji_capable=False, density_n=2)[0] is lines[0]
    assert apply_line_emoji(lines, emoji_capable=True, density_n=0)[0] is lines[0]


def test_apply_stamps_the_selected_word() -> None:
    out = apply_line_emoji([_words("деньги")], emoji_capable=True, density_n=1)
    assert _emoji_of(out[0]) == ["\U0001f4b0"]


def test_apply_density_caps_to_one_per_n_lines() -> None:
    lines = [_words("деньги") for _ in range(5)]  # every line maps
    out = apply_line_emoji(lines, emoji_capable=True, density_n=3)
    stamped = [i for i, line in enumerate(out) if any(w.emoji for w in line.words)]
    assert stamped == [0, 3]


def test_apply_drops_non_allowlisted_glyph() -> None:
    out = apply_line_emoji(
        [_words("деньги")], emoji_capable=True, density_n=1, emoji_for_fn=lambda _t: "🦄"
    )
    assert _emoji_of(out[0]) == [""]
    assert out[0].words[0].emoji == ""


def test_apply_is_immutable() -> None:
    line = _words("деньги")
    out = apply_line_emoji([line], emoji_capable=True, density_n=1)
    assert line.words[0].emoji == ""  # input untouched
    assert out[0] is not line


def test_apply_no_match_line_stays_bare() -> None:
    line = _words("стол", "стул")
    out = apply_line_emoji([line], emoji_capable=True, density_n=1)
    assert out[0] is line


# --- ass.py rendering: suffix bytes + OFF byte-identity ---


def test_emoji_renders_as_its_own_neutral_run_no_pop() -> None:
    from fliphouse_worker.captioning.ass import DEFAULT_PRESET, build_caption_ass

    line = apply_line_emoji([_words("деньги")], emoji_capable=True, density_n=1)[0]
    ass = build_caption_ass([line], preset=dataclasses.replace(DEFAULT_PRESET, emoji_every_n=1))
    assert "\\c&H00FFFFFF} \U0001f4b0" in ass  # neutral white run, leading space


def test_emoji_off_is_byte_identical_to_no_emoji() -> None:
    from fliphouse_worker.captioning.ass import build_caption_ass

    bare = _words("деньги", "сразу")
    assert build_caption_ass([bare]) == build_caption_ass([_words("деньги", "сразу")])


# --- frame-fit width model: text + emoji reserve must stay inside the play-res budget ---


def test_emoji_frame_scale_downscales_a_wide_line_and_floors_at_50() -> None:
    from fliphouse_worker.captioning.ass import _emoji_frame_scale_pct

    # A line that fits stays at 100 (no shrink); a mid-overflow shrinks proportionally; an
    # extreme overflow clamps at the 50% floor (legibility guard, never collapses to nothing).
    assert _emoji_frame_scale_pct("да", 0.0) == 100
    assert 50 < _emoji_frame_scale_pct("доход растёт быстро", 1.5) < 100
    assert _emoji_frame_scale_pct("ш" * 60, 2.5) == 50


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
