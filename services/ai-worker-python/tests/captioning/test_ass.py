"""GOLDEN tests for the pure ASS builder — colour byte-order, \\k karaoke, grouping."""

from __future__ import annotations

import pytest

from fliphouse_worker.captioning.ass import (
    ACTIVE_COLOUR,
    BASE_COLOUR,
    FONT_NAME,
    CaptionLine,
    build_caption_ass,
    caption_y,
    escape_ass_text,
    group_caption_lines,
)
from fliphouse_worker.captioning.segments import CaptionWord

# --- the #1 ASS bug: colour is &HAABBGGRR (alpha-blue-green-red, AA=00=opaque) ---


def test_base_colour_is_opaque_white_in_abgr_byte_order() -> None:
    # White is symmetric, but the ALPHA byte must be 00 (opaque), not FF (invisible).
    assert BASE_COLOUR == "&H00FFFFFF"


def test_active_colour_is_opaque_vermillion_in_reversed_byte_order() -> None:
    # CSS #FF3B30 (R=FF G=3B B=30) reversed to ASS &HAABBGGRR → AA=00 BB=30 GG=3B RR=FF.
    # A naive CSS-order &H00FF3B30 would render the WRONG colour (blue-ish) — pin BGR.
    assert ACTIVE_COLOUR == "&H00303BFF"


def test_style_line_is_pinned_byte_for_byte() -> None:
    ass = build_caption_ass([])
    # The exact V4+ Style row. Fontname MUST equal what fc-list reports for the
    # vendored static (Montserrat ExtraBold); BorderStyle 1 + Outline 4 + Shadow 2;
    # Alignment 2 (bottom-centre); Bold=-1; PrimaryColour = opaque white base.
    expected = (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,40,40,210,1"
    )
    assert expected in ass
    assert FONT_NAME == "Montserrat ExtraBold"


def test_script_info_pins_playres_and_render_flags() -> None:
    ass = build_caption_ass([])
    assert "PlayResX: 1080" in ass
    assert "PlayResY: 1920" in ass
    assert "ScaledBorderAndShadow: yes" in ass
    assert "WrapStyle: 2" in ass


# --- native \k karaoke: centiseconds, white base flips to active per word ---


def test_dialogue_emits_per_word_k_in_centiseconds() -> None:
    line = CaptionLine(
        start=1.0,
        end=2.0,
        words=(
            CaptionWord(text="да", start=1.0, end=1.4),
            CaptionWord(text="нет", start=1.4, end=2.0),
        ),
    )
    ass = build_caption_ass([line])
    # 0.40 s → 40 cs, 0.60 s → 60 cs; the active flip uses an inline \c override.
    assert "{\\k40}" in ass
    assert "{\\k60}" in ass
    assert f"{{\\c{ACTIVE_COLOUR}}}" in ass
    # Dialogue start/end are ASS H:MM:SS.cc centiseconds.
    assert "Dialogue: 0,0:00:01.00,0:00:02.00,Caption," in ass


def test_dialogue_rounds_negative_or_zero_duration_word_to_min_one_cs() -> None:
    # A zero-length word must still advance \k by at least 1cs or karaoke desyncs.
    line = CaptionLine(
        start=0.0,
        end=0.5,
        words=(CaptionWord(text="x", start=0.0, end=0.0),),
    )
    ass = build_caption_ass([line])
    assert "{\\k1}" in ass


# --- escaping: literal braces / backslashes in caption TEXT must be neutralised ---


def test_escape_ass_text_neutralises_override_metacharacters() -> None:
    # { } and \ start/feed ASS override blocks — a raw one corrupts the line.
    assert escape_ass_text("a{b}c\\d") == "a\\{b\\}c\\\\d"


def test_build_ass_escapes_braces_in_a_word() -> None:
    line = CaptionLine(
        start=0.0,
        end=1.0,
        words=(CaptionWord(text="{evil}", start=0.0, end=1.0),),
    )
    ass = build_caption_ass([line])
    assert "\\{evil\\}" in ass


# --- group_caption_lines: 1-3 words/line, greedy break on char budget ---


def test_groups_into_1_to_3_words_per_line() -> None:
    words = tuple(CaptionWord(text=f"w{i}", start=float(i), end=float(i) + 0.5) for i in range(7))
    lines = group_caption_lines(words)
    for line in lines:
        assert 1 <= len(line.words) <= 3
    # Every word is preserved in order.
    flat = [w.text for line in lines for w in line.words]
    assert flat == [f"w{i}" for i in range(7)]


def test_greedy_break_on_char_budget_keeps_short_lines_dense() -> None:
    # Three tiny words fit one line (≤16 chars); a long word forces an early break.
    words = (
        CaptionWord(text="ab", start=0.0, end=0.4),
        CaptionWord(text="cd", start=0.4, end=0.8),
        CaptionWord(text="оченьдлинноеслово", start=0.8, end=1.2),
    )
    lines = group_caption_lines(words)
    assert [w.text for w in lines[0].words] == ["ab", "cd"]
    assert [w.text for w in lines[1].words] == ["оченьдлинноеслово"]


def test_line_start_end_span_the_member_words() -> None:
    words = (
        CaptionWord(text="a", start=1.0, end=1.5),
        CaptionWord(text="b", start=1.5, end=2.2),
    )
    lines = group_caption_lines(words)
    assert lines[0].start == 1.0
    assert lines[0].end == 2.2


def test_group_empty_is_empty() -> None:
    assert group_caption_lines(()) == []


# --- caption_y: avoid a detected source caption band + face safe-zone ---


def test_caption_y_default_lower_third_when_no_source_band() -> None:
    assert caption_y(None) == 210


def test_caption_y_lifts_above_a_high_source_caption_band() -> None:
    # A source band whose top sits high pushes our margin UP (larger MarginV) so the
    # two never overlap. Band recorded in SOURCE pixels; the lift is monotonic.
    low_band = {"y_top": 1700, "y_bottom": 1800, "confidence": 0.9}
    high_band = {"y_top": 1400, "y_bottom": 1500, "confidence": 0.9}
    assert caption_y(high_band) > caption_y(low_band)


def test_caption_y_ignores_a_malformed_band() -> None:
    assert caption_y({"confidence": 0.5}) == 210


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
