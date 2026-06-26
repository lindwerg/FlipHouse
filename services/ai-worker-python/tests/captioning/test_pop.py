"""P3-A3 — active-word POP via libass ``\\t``: composition, frame-clamp, byte-identity.

The pop is gated behind ``preset.pop`` (False in DEFAULT_PRESET → golden untouched).
When on, the spoken word pulses base→peak→base via two event-relative ``\\t`` and the
peak is clamped per word against the REAL font advances so a Russian line can never
grow off the 1080 frame (the Latin ``len·0.62`` heuristic under-estimates Cyrillic and
must NOT gate this).
"""

from __future__ import annotations

import dataclasses

from fliphouse_worker.captioning.ass import (
    DEFAULT_PRESET,
    FONT_SIZE,
    PLAY_RES_X,
    POP_FALL_MS,
    POP_FRAME_BUDGET_PX,
    POP_PEAK_PCT,
    POP_RISE_MS,
    CaptionLine,
    _line_body,
    _line_scale_pct,
    _pop_peak_pct,
    build_caption_ass,
)
from fliphouse_worker.captioning.metrics import text_width_em
from fliphouse_worker.captioning.segments import CaptionWord

POP_PRESET = dataclasses.replace(DEFAULT_PRESET, pop=True)


def _line(*pairs: tuple[str, float, float]) -> CaptionLine:
    words = tuple(CaptionWord(text=t, start=s, end=e) for t, s, e in pairs)
    return CaptionLine(start=words[0].start, end=words[-1].end, words=words)


def _popped_width_px(visible: str, active: str, base: int, peak: int) -> float:
    others_em = text_width_em(visible) - text_width_em(active)
    return others_em * FONT_SIZE * base / 100.0 + text_width_em(active) * FONT_SIZE * peak / 100.0


# --- byte-identity: pop OFF reproduces the historical body verbatim ---


def test_pop_false_is_byte_identical_to_default_preset() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert build_caption_ass([line], preset=dataclasses.replace(DEFAULT_PRESET, pop=False)) == (
        build_caption_ass([line])
    )


def test_pop_false_emits_no_transform_or_per_word_scale_on_a_fitting_line() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    ass = build_caption_ass([line])  # DEFAULT_PRESET.pop is False
    assert "\\t(" not in ass
    assert "\\fscx" not in ass  # a short fitting line carries no scale override at all


def test_pop_changes_the_bytes_versus_default() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert build_caption_ass([line], preset=POP_PRESET) != build_caption_ass([line])


# --- the active word pulses base→peak→base with two event-relative \t ---


def test_active_word_carries_two_transforms_returning_to_base() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    body = _line_body(line, 0, POP_PRESET)  # 'да' active, narrow line → full pop
    active_block = body.split(" ", 1)[0]
    assert active_block == (
        f"{{\\fscx100\\fscy100"
        f"\\t(0,{POP_RISE_MS},\\fscx{POP_PEAK_PCT}\\fscy{POP_PEAK_PCT})"
        f"\\t({POP_RISE_MS},{POP_RISE_MS + POP_FALL_MS},\\fscx100\\fscy100)"
        f"\\c{DEFAULT_PRESET.active_colour}}}да"
    )


def test_non_active_words_reset_to_base_and_carry_no_transform() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    body = _line_body(line, 0, POP_PRESET)  # 'нет' is non-active
    non_active_block = body.split(" ", 1)[1]
    assert non_active_block == f"{{\\fscx100\\fscy100\\c{DEFAULT_PRESET.base_colour}}}нет"
    assert "\\t(" not in non_active_block  # no animated-scale bleed into the neighbour


def test_pop_keeps_exactly_one_active_word_per_event() -> None:
    line = _line(("раз", 0.0, 0.3), ("два", 0.3, 0.6), ("три", 0.6, 1.0))
    ass = build_caption_ass([line], preset=POP_PRESET)
    dialogues = [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]
    assert len(dialogues) == 3
    for row in dialogues:
        assert row.count(f"\\c{DEFAULT_PRESET.active_colour}") == 1


# --- the frame-clamp: a popped word never grows off the 1080 frame ---


def test_narrow_line_pops_to_full_nominal_peak() -> None:
    assert _pop_peak_pct("да нет", "да", 100) == POP_PEAK_PCT


def test_wide_russian_line_suppresses_the_pop_no_transform() -> None:
    # 'больше шума' renders ~1069px at rest — wider than the budget. The Latin
    # len·0.62 heuristic would (wrongly) think it fits and permit a clipping pop;
    # the real-metric clamp instead suppresses it to base (no \t).
    line = _line(("больше", 0.0, 0.5), ("шума", 0.5, 1.0))
    assert _pop_peak_pct("больше шума", "больше", 100) == 100
    body = _line_body(line, 0, POP_PRESET)
    assert "\\t(" not in body  # no pop emitted on a line with no frame headroom


def test_pop_composes_multiplicatively_on_autoscale_base() -> None:
    # A long token autoscaled below 100 pops on TOP of that shrunk base (never a flat
    # 115 that ignores the shrink), still clamped within budget.
    visible, active = "заработок сразу", "заработок"
    base = _line_scale_pct(visible)
    assert base < 100  # autoscale fired
    peak = _pop_peak_pct(visible, active, base)
    assert base < peak <= base * POP_PEAK_PCT // 100
    assert _popped_width_px(visible, active, base, peak) <= POP_FRAME_BUDGET_PX


def test_popped_width_never_exceeds_max_of_resting_and_budget_for_russian_lines() -> None:
    # The A3 safety invariant: pop NEVER renders wider than the line already does at
    # rest, and whenever it grows it stays within the frame budget.
    cases = [
        ("да нет", ("да", "нет")),
        ("больше шума", ("больше", "шума")),
        ("деньги", ("деньги",)),
        ("СТОП ШУМ", ("СТОП", "ШУМ")),
        ("заработок сразу", ("заработок", "сразу")),
        ("предприниматель", ("предприниматель",)),
    ]
    for visible, actives in cases:
        base = max(_line_scale_pct(visible), 1)
        resting = _popped_width_px(visible, visible, base, base)
        for active in actives:
            peak = _pop_peak_pct(visible, active, base)
            popped = _popped_width_px(visible, active, base, peak)
            assert peak >= base  # never an inverse pop
            assert popped <= max(resting, POP_FRAME_BUDGET_PX) + 1e-6
            assert popped <= max(resting, PLAY_RES_X) + 1e-6


def test_pop_peak_returns_base_for_an_empty_active_word() -> None:
    # Guards the active_em<=0 path: an empty word yields no pop (peak==base).
    assert _pop_peak_pct(" ", "", 100) == 100


def test_empty_active_word_emits_no_transform_in_the_body() -> None:
    line = _line(("", 0.0, 0.5), ("тут", 0.5, 1.0))
    body = _line_body(line, 0, POP_PRESET)
    active_block = body.split(" ", 1)[0]
    assert active_block == f"{{\\fscx100\\fscy100\\c{DEFAULT_PRESET.active_colour}}}"
    assert "\\t(" not in active_block
