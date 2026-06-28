"""GOLDEN tests for the pure ASS builder — colour byte-order, per-word reveal, grouping."""

from __future__ import annotations

import dataclasses

import pytest

from fliphouse_worker.captioning.ass import (
    ACTIVE_COLOUR,
    BASE_COLOUR,
    CAPTION_PRESETS,
    CONTRAST_BAND_BS3,
    CONTRAST_BAND_TRANSLUCENT,
    CONTRAST_OUTLINE,
    DEFAULT_MARGIN_V,
    DEFAULT_PRESET,
    FONT_NAME,
    GAP_SPLIT_S,
    MARGIN_LR,
    MAX_LINE_CHARS,
    MAX_WORD_HOLD_S,
    PLAY_RES_Y,
    USABLE_WIDTH_PX,
    CaptionLine,
    _resolve_word_colour,
    build_caption_ass,
    caption_y,
    escape_ass_text,
    estimate_line_width_px,
    group_caption_lines,
)
from fliphouse_worker.captioning.preset import _ASS_COLOUR_RE
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
    # MarginV is 430 (SAFE_BOTTOM_PX 370 + 60 gap): the caption band bottom sits at
    # y = 1920 - 430 = 1490, inside the documented safe caption_band [1180, 1600] and
    # ABOVE the platform bottom-UI cluster (≈370px). It is no longer the old 210
    # lower-third, which placed the band bottom at y=1710 — occluded by TikTok/Reels UI.
    expected = (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,40,40,430,1"
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


def test_lead_offset_advances_active_window_without_overlap_or_negative_time() -> None:
    # P3-A2: the highlight starts preset.lead_ms BEFORE the word is spoken.
    import dataclasses

    from fliphouse_worker.captioning.ass import DEFAULT_PRESET

    preset = dataclasses.replace(DEFAULT_PRESET, lead_ms=70)
    line = CaptionLine(
        start=0.9,
        end=2.0,
        words=(
            CaptionWord(text="да", start=0.9, end=1.4),
            CaptionWord(text="нет", start=0.88, end=2.0),  # non-monotonic → clamps to prev
            CaptionWord(text="точно", start=1.5, end=2.0),
        ),
    )
    ass = build_caption_ass([line], preset=preset)
    starts = [ln.split(",")[1] for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    # word 0: 0.9 - 0.07 = 0.83
    assert starts[0] == "0:00:00.83"
    # word 1: 0.88 - 0.07 = 0.81 < prev 0.83 → clamped to 0.83 (never earlier than i-1)
    assert starts[1] == "0:00:00.83"
    # word 2: 1.5 - 0.07 = 1.43, monotonic
    assert starts[2] == "0:00:01.43"


def test_lead_clamps_first_word_to_non_negative_time() -> None:
    import dataclasses

    from fliphouse_worker.captioning.ass import DEFAULT_PRESET

    preset = dataclasses.replace(DEFAULT_PRESET, lead_ms=70)
    line = CaptionLine(
        start=0.05,
        end=0.5,
        words=(CaptionWord(text="а", start=0.05, end=0.5),),
    )
    ass = build_caption_ass([line], preset=preset)
    # 0.05 - 0.07 = -0.02 → clamped to 0.0
    assert "Dialogue: 0,0:00:00.00," in ass


def test_lead_ms_zero_reproduces_current_windows() -> None:
    line = CaptionLine(
        start=1.0,
        end=2.0,
        words=(
            CaptionWord(text="да", start=1.0, end=1.4),
            CaptionWord(text="нет", start=1.4, end=2.0),
        ),
    )
    # default lead_ms is 0 → byte-identical to the historical windows.
    ass = build_caption_ass([line])
    assert "Dialogue: 0,0:00:01.00,0:00:01.40,Caption," in ass
    assert "Dialogue: 0,0:00:01.40,0:00:02.00,Caption," in ass


def test_intra_line_pause_caps_the_non_last_row_hold() -> None:
    # P3-C1: word 0 is followed by a 3s mid-line pause; its row would run 0.0→3.0 (the
    # next word's start). The cap holds it at MAX_WORD_HOLD_S instead of freezing.
    line = CaptionLine(
        start=0.0,
        end=3.5,
        words=(CaptionWord("раз", 0.0, 0.4), CaptionWord("два", 3.0, 3.5)),
    )
    ass = build_caption_ass([line])
    assert MAX_WORD_HOLD_S == 1.2
    assert "Dialogue: 0,0:00:00.00,0:00:01.20,Caption," in ass  # capped row 0
    assert "0:00:00.00,0:00:03.00" not in ass  # NOT the frozen full-pause hold


def test_long_inter_word_gap_splits_the_line() -> None:
    # P3-C1: a gap > GAP_SPLIT_S starts a new line; the pre-pause word ends the first.
    a = CaptionWord("раз", 0.0, 0.4)
    b = CaptionWord("два", 3.4, 3.8)  # gap 3.0s > GAP_SPLIT_S
    assert GAP_SPLIT_S == 0.8
    lines = group_caption_lines([a, b])
    assert len(lines) == 2
    assert lines[0].words == (a,)
    assert lines[1].words == (b,)
    assert lines[0].end == 0.4  # first line ends at its own word.end, no linger


def test_lone_slow_word_runs_full_not_truncated() -> None:
    # P3-C1 trims trailing-SILENCE linger, never a word's own speech: a lone word spoken
    # slowly over 2s shows for the full 2s (its row ends at word.end, not cut at 1.2s).
    line = CaptionLine(start=0.0, end=2.0, words=(CaptionWord("деньги", 0.0, 2.0),))
    ass = build_caption_ass([line])
    assert "0:00:00.00,0:00:02.00" in ass
    assert "0:00:00.00,0:00:01.20" not in ass


def test_slow_non_last_word_shows_full_speech_then_trims_the_gap() -> None:
    # A 2s non-last word with a 0.5s gap to the next (no split): the word shows in FULL
    # (to its own end 2.0); only the trailing-silence linger up to the next start is trimmed.
    line = CaptionLine(
        start=0.0,
        end=3.0,
        words=(CaptionWord("раз", 0.0, 2.0), CaptionWord("два", 2.5, 3.0)),
    )
    ass = build_caption_ass([line])
    assert "0:00:00.00,0:00:02.00" in ass  # word 0 shown in full, the 0.5s gap trimmed off


def test_trailing_silence_after_last_word_stays_empty() -> None:
    # Regression: a 5s line span with a short last word does NOT render to 5s (the last
    # word already ends at word.end; the cap does not extend it).
    line = CaptionLine(start=0.0, end=5.0, words=(CaptionWord("всё", 0.0, 0.4),))
    ass = build_caption_ass([line])
    assert "0:00:05.00" not in ass


def test_short_gaps_do_not_split_or_cap_normal_speech() -> None:
    # Byte-identity guard: sub-threshold gaps + sub-cap windows leave grouping and rows
    # exactly as before C1 (the normal-speech path is untouched).
    words = [CaptionWord("а", 0.0, 0.4), CaptionWord("б", 0.5, 0.9), CaptionWord("в", 1.0, 1.4)]
    assert len(group_caption_lines(words)) == 1  # 0.1s gaps never split


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


def test_caption_y_default_clears_platform_bottom_ui_when_no_source_band() -> None:
    # Resting margin clears the platform bottom-UI safe zone (no source band case).
    assert caption_y(None) == 430


def test_caption_y_lifts_above_a_high_source_caption_band() -> None:
    # A source band whose top sits high pushes our margin UP (larger MarginV) so the
    # two never overlap. Band recorded in SOURCE pixels; the lift is monotonic.
    low_band = {"y_top": 1700, "y_bottom": 1800, "confidence": 0.9}
    high_band = {"y_top": 1400, "y_bottom": 1500, "confidence": 0.9}
    assert caption_y(high_band) > caption_y(low_band)


def test_caption_y_ignores_a_malformed_band() -> None:
    assert caption_y({"confidence": 0.5}) == 430


# --- VIS-1: caption band clears the platform bottom-UI safe zone ---


def test_default_margin_band_bottom_sits_inside_the_safe_caption_band() -> None:
    # docs/01 §2 (safe_zones.py) puts the cross-platform caption_band at y∈[1180,1600].
    # The band bottom (y = PlayResY - MarginV) must land inside it: clear of the
    # platform bottom UI (below) AND of an upper-third speaker crop (above centre 960).
    band_bottom = PLAY_RES_Y - DEFAULT_MARGIN_V
    assert 1180 <= band_bottom <= 1600
    assert band_bottom > 960  # stays in the lower half, never over the face crop


def test_default_margin_clears_the_platform_bottom_ui_cluster() -> None:
    # TikTok/Reels/Shorts ads occlude ≈370px at the bottom; the band bottom must sit
    # at least that far up from the frame bottom (1920) with margin to spare.
    band_bottom = PLAY_RES_Y - DEFAULT_MARGIN_V
    assert PLAY_RES_Y - band_bottom >= 370


# --- VIS-2: line-width budget — no built line overflows the usable frame width ---

# A corpus of long Russian words (and a worst-case 3-word pack) the packer must never
# let exceed the usable width once grouped — long single tokens auto-scale instead.
_LONG_RU_WORDS = (
    "предприниматель",
    "сотрудничество",
    "ответственность",
    "достопримечательность",
    "несовершеннолетний",
    "конкурентоспособность",
)


def test_no_grouped_line_exceeds_usable_width() -> None:
    # Build a stream mixing long and short RU words; after grouping, every line's
    # estimated width must be within the usable frame width (1000px) so libass never
    # force-wraps — except a LONE token wider than the budget, which gets its own line
    # and is handled by the autoscale safety net (asserted separately below).
    stream = []
    t = 0.0
    for w in (*_LONG_RU_WORDS, "да", "нет", "и", "вот", "так", "что"):
        stream.append(CaptionWord(text=w, start=t, end=t + 0.4))
        t += 0.4
    lines = group_caption_lines(tuple(stream))
    for line in lines:
        visible = " ".join(w.text for w in line.words)
        width = estimate_line_width_px(visible)
        is_lone_overlong = len(line.words) == 1 and width > USABLE_WIDTH_PX
        assert width <= USABLE_WIDTH_PX or is_lone_overlong


def test_char_budget_is_calibrated_to_the_font_so_a_full_line_fits() -> None:
    # A MAX_LINE_CHARS-long single token must fit the usable width (the packer's
    # invariant). If the font or budget drifts apart this fails loudly.
    assert estimate_line_width_px("ы" * MAX_LINE_CHARS) <= USABLE_WIDTH_PX
    # ...and one char over the budget would NOT fit (the budget is the real limit).
    assert estimate_line_width_px("ы" * (MAX_LINE_CHARS + 4)) > USABLE_WIDTH_PX


def test_overlong_single_word_is_autoscaled_to_fit_not_clipped() -> None:
    # 'достопримечательность' (21 chars) overflows even alone → the first word's
    # override carries an \fscx/\fscy shrink so it fits instead of clipping the frame.
    line = CaptionLine(
        start=0.0,
        end=1.0,
        words=(CaptionWord(text="достопримечательность", start=0.0, end=1.0),),
    )
    ass = build_caption_ass([line])
    assert "\\fscx" in ass and "\\fscy" in ass
    # The scaled width must fit the usable frame width.
    import re

    pct = int(re.search(r"\\fscx(\d+)", ass).group(1))
    scaled = estimate_line_width_px("достопримечательность") * pct / 100
    assert scaled <= USABLE_WIDTH_PX


def test_short_line_has_no_autoscale_override_so_the_golden_is_stable() -> None:
    # A normal short line fits at 100% → NO \fscx/\fscy tag is emitted (keeps the
    # per-word karaoke colour rows byte-identical to the golden).
    line = CaptionLine(
        start=0.0,
        end=1.0,
        words=(
            CaptionWord(text="да", start=0.0, end=0.4),
            CaptionWord(text="нет", start=0.4, end=1.0),
        ),
    )
    ass = build_caption_ass([line])
    assert "\\fscx" not in ass


def test_autoscale_does_not_break_per_word_karaoke_colouring() -> None:
    # Even on an autoscaled lone word the ACTIVE colour is still applied — the scale
    # tag is PREPENDED to the existing \c override, never replacing it.
    line = CaptionLine(
        start=0.0,
        end=1.0,
        words=(CaptionWord(text="несовершеннолетний", start=0.0, end=1.0),),
    )
    ass = build_caption_ass([line])
    assert f"\\c{ACTIVE_COLOUR}" in ass


def test_margin_lr_unchanged_so_usable_width_holds() -> None:
    # The usable-width budget assumes the 40px L/R margins; pin them so a change to
    # MARGIN_LR can't silently invalidate the char budget.
    assert MARGIN_LR == 40
    assert USABLE_WIDTH_PX == 1000


# --- P3-A6: contrast band (BorderStyle preset knob) ---


def _a6_lines() -> list[CaptionLine]:
    return [
        CaptionLine(
            start=0.0,
            end=1.0,
            words=(
                CaptionWord(text="контраст", start=0.0, end=0.5),
                CaptionWord(text="band", start=0.5, end=1.0),
            ),
        )
    ]


def test_contrast_band_bs3_style_row_is_pinned_byte_for_byte() -> None:
    # Opaque box per line: BorderStyle=3, box FILL = OutlineColour &H00101010, padding
    # (Outline) 8, Shadow 0. Exactly one band rectangle behind each line.
    ass = build_caption_ass(_a6_lines(), preset=CONTRAST_BAND_BS3)
    assert (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H00101010,&H64000000,"
        "-1,0,0,0,100,100,0,0,3,8,0,2,40,40,430,1"
    ) in ass


def test_contrast_band_translucent_carries_50pct_alpha_box_fill() -> None:
    ass = build_caption_ass(_a6_lines(), preset=CONTRAST_BAND_TRANSLUCENT)
    assert (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H80101010,&H64000000,"
        "-1,0,0,0,100,100,0,0,3,8,0,2,40,40,430,1"
    ) in ass


def test_contrast_outline_is_a_no_box_halo_bump() -> None:
    # border_style stays 1 (no box); only the outline/shadow thicken (6/3).
    ass = build_caption_ass(_a6_lines(), preset=CONTRAST_OUTLINE)
    assert (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,6,3,2,40,40,430,1"
    ) in ass


def _events_section(ass: str) -> str:
    return ass.split("[Events]", 1)[1]


def test_border_style_leaves_every_dialogue_body_byte_identical() -> None:
    # The band knob is a Style-row field only; it must not touch any Dialogue body, so the
    # per-word reveal/colour/timing stay character-for-character identical across presets.
    lines = _a6_lines()
    default_events = _events_section(build_caption_ass(lines, preset=DEFAULT_PRESET))
    band_events = _events_section(build_caption_ass(lines, preset=CONTRAST_BAND_BS3))
    assert band_events == default_events


def test_caption_presets_registry_box_looks_disable_pop() -> None:
    # A bs=3 box tracks the rendered text bbox; composing it with the active-word pop would
    # pulse the band once per word. Every box preset must keep pop=False.
    for name, preset in CAPTION_PRESETS.items():
        if preset.border_style != 1:
            assert preset.pop is False, f"box preset {name!r} must not enable pop"


# --- P3-A4: keyword second colour (precedence active > keyword > base) ---

_KEYWORD_PRESET = dataclasses.replace(DEFAULT_PRESET, keyword_colour="&H000AD6FF")


def _kw_line() -> CaptionLine:
    # word 0 is the emphasised keyword.
    return CaptionLine(
        start=0.0,
        end=1.0,
        words=(
            CaptionWord(text="деньги", start=0.0, end=0.4, emphasis=True),
            CaptionWord(text="любят", start=0.4, end=0.7),
            CaptionWord(text="счёт", start=0.7, end=1.0),
        ),
    )


def test_resolve_word_colour_precedence_active_over_keyword_over_base() -> None:
    kw_word = CaptionWord(text="x", start=0.0, end=1.0, emphasis=True)
    plain = CaptionWord(text="y", start=0.0, end=1.0)
    # active wins even on the keyword word (the one event it is spoken).
    assert _resolve_word_colour(0, 0, kw_word, _KEYWORD_PRESET) == _KEYWORD_PRESET.active_colour
    # non-active emphasised word → keyword colour.
    assert _resolve_word_colour(1, 0, kw_word, _KEYWORD_PRESET) == _KEYWORD_PRESET.keyword_colour
    # non-emphasised word → base.
    assert _resolve_word_colour(1, 0, plain, _KEYWORD_PRESET) == _KEYWORD_PRESET.base_colour
    # keyword_colour None → never keyword, even when emphasised (byte-identical default).
    assert _resolve_word_colour(1, 0, kw_word, DEFAULT_PRESET) == DEFAULT_PRESET.base_colour


def test_keyword_colour_paints_emphasised_word_in_non_active_events() -> None:
    ass = build_caption_ass([_kw_line()], preset=_KEYWORD_PRESET)
    events = _events_section(ass)
    # The keyword word renders keyword colour when NOT the active word, active colour when it is.
    assert "\\c&H000AD6FF}деньги" in events  # non-active events of the keyword word
    assert "\\c&H00303BFF}деньги" in events  # the one event where it is the active (spoken) word


def test_keyword_colour_composes_in_pop_branch() -> None:
    ass = build_caption_ass([_kw_line()], preset=dataclasses.replace(_KEYWORD_PRESET, pop=True))
    events = _events_section(ass)
    assert "\\c&H000AD6FF}деньги" in events  # keyword colour survives the pop branch too


def test_default_render_is_byte_identical_even_when_words_carry_emphasis() -> None:
    # emphasis on a word must be inert under DEFAULT_PRESET (keyword_colour=None).
    emph = CaptionLine(
        start=0.0,
        end=1.0,
        words=(
            CaptionWord(text="деньги", start=0.0, end=0.5, emphasis=True),
            CaptionWord(text="любят", start=0.5, end=1.0),
        ),
    )
    plain = CaptionLine(
        start=0.0,
        end=1.0,
        words=(
            CaptionWord(text="деньги", start=0.0, end=0.5),
            CaptionWord(text="любят", start=0.5, end=1.0),
        ),
    )
    assert build_caption_ass([emph]) == build_caption_ass([plain])


def test_every_shipped_preset_colour_matches_the_ass_hex_regex() -> None:
    # The __post_init__ colour regex validates base/active/keyword; assert every registry
    # preset constructs (it would raise at import otherwise) and carries valid hex.
    for name, preset in CAPTION_PRESETS.items():
        assert _ASS_COLOUR_RE.fullmatch(preset.base_colour), name
        assert _ASS_COLOUR_RE.fullmatch(preset.active_colour), name
        if preset.keyword_colour is not None:
            assert _ASS_COLOUR_RE.fullmatch(preset.keyword_colour), name


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
