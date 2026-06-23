"""GOLDEN tests for the pure ASS builder — colour byte-order, per-word reveal, grouping."""

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


# --- per-word reveal: one Dialogue per word, spoken word vermillion, rest white ---


def test_emits_one_dialogue_per_word_with_only_the_spoken_word_active() -> None:
    line = CaptionLine(
        start=1.0,
        end=2.0,
        words=(
            CaptionWord(text="да", start=1.0, end=1.4),
            CaptionWord(text="нет", start=1.4, end=2.0),
        ),
    )
    ass = build_caption_ass([line])
    dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    # ONE row PER WORD (per-word reveal), not one static row per line.
    assert len(dialogues) == 2
    # word 0: 'да' active (vermillion), 'нет' base (white); a NON-last word spans
    # [1.0, next.start=1.4); words are SPACE-joined.
    assert (
        f"Dialogue: 0,0:00:01.00,0:00:01.40,Caption,,0,0,0,,"
        f"{{\\c{ACTIVE_COLOUR}}}да {{\\c{BASE_COLOUR}}}нет"
    ) in ass
    # word 1: 'нет' active; the LAST word runs to its own end (2.0).
    assert (
        f"Dialogue: 0,0:00:01.40,0:00:02.00,Caption,,0,0,0,,"
        f"{{\\c{BASE_COLOUR}}}да {{\\c{ACTIVE_COLOUR}}}нет"
    ) in ass


def test_words_are_space_joined_so_tokens_never_collide() -> None:
    # The #2 caption bug: lstripped source words concatenated with NO space rendered
    # "лишили$9млрд". Per-word rows must SPACE-join the tokens.
    line = CaptionLine(
        start=0.0,
        end=1.0,
        words=(
            CaptionWord(text="лишили", start=0.0, end=0.4),
            CaptionWord(text="$9", start=0.4, end=0.7),
            CaptionWord(text="млрд", start=0.7, end=1.0),
        ),
    )
    ass = build_caption_ass([line])
    assert "лишили {" in ass  # a space precedes the next word's override block
    assert "$9 {" in ass
    assert "лишили$9" not in ass


def test_degenerate_word_window_is_nudged_so_libass_keeps_the_row() -> None:
    # A single zero-length last word: seg_end <= seg_start → nudged to start+0.01.
    line = CaptionLine(
        start=0.0,
        end=0.0,
        words=(CaptionWord(text="x", start=0.0, end=0.0),),
    )
    ass = build_caption_ass([line])
    assert "Dialogue: 0,0:00:00.00,0:00:00.01,Caption," in ass


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
