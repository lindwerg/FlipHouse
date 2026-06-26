"""P3-A5 — one-shot caption fade-in via libass ``\\fad``: first-event-only, no strobe.

The fade is gated behind ``preset.fade_in_ms`` (0 in DEFAULT_PRESET → golden untouched).
When positive, ONLY the FIRST event of each line carries ``\\fad(F,0)`` (fade-in only);
interior per-word events carry NO ``\\fad`` — each interior Dialogue re-spans the whole
line, so a fade on every event would re-fade the line per word and read as a STROBE.
``F`` is clamped strictly below the first event's on-screen window (centisecond-quantised
to match ``_ass_timestamp``) so the entrance always completes inside the word window.
``\\fad`` (line alpha) is orthogonal to ``\\t`` (pop scale) and ``lead_ms`` (start shift),
so it composes with A2/A3 without conflict.
"""

from __future__ import annotations

import dataclasses

import pytest

from fliphouse_worker.captioning.ass import (
    DEFAULT_PRESET,
    POP_FALL_MS,
    POP_PEAK_PCT,
    POP_RISE_MS,
    CaptionLine,
    _line_body,
    build_caption_ass,
)
from fliphouse_worker.captioning.preset import CaptionPreset
from fliphouse_worker.captioning.segments import CaptionWord

FADE_MS = 120
FADE_PRESET = dataclasses.replace(DEFAULT_PRESET, fade_in_ms=FADE_MS)
POP_PRESET = dataclasses.replace(DEFAULT_PRESET, pop=True)


def _line(*pairs: tuple[str, float, float]) -> CaptionLine:
    words = tuple(CaptionWord(text=t, start=s, end=e) for t, s, e in pairs)
    return CaptionLine(start=words[0].start, end=words[-1].end, words=words)


def _dialogues(ass: str) -> list[str]:
    return [ln for ln in ass.splitlines() if ln.startswith("Dialogue:")]


# --- byte-identity: fade OFF reproduces the golden verbatim ---


def test_fade_in_ms_zero_is_byte_identical_to_default_preset() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert build_caption_ass(
        [line], preset=dataclasses.replace(DEFAULT_PRESET, fade_in_ms=0)
    ) == build_caption_ass([line])


def test_default_preset_unchanged_with_new_field() -> None:
    # The new field defaults to 0; a preset built without it equals DEFAULT_PRESET.
    assert DEFAULT_PRESET.fade_in_ms == 0
    assert dataclasses.replace(DEFAULT_PRESET, fade_in_ms=0) == DEFAULT_PRESET


def test_pop_preset_default_fade_zero_is_byte_identical() -> None:
    # POP_PRESET leaves fade at 0 → it must not perturb the A3 pop golden.
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert "\\fad(" not in build_caption_ass([line], preset=POP_PRESET)


def test_fade_changes_the_bytes_versus_default() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert build_caption_ass([line], preset=FADE_PRESET) != build_caption_ass([line])


# --- the anti-strobe invariant: \fad ONLY on the first event of the line ---


def test_fade_appears_only_on_the_first_event_block() -> None:
    line = _line(("раз", 0.0, 0.4), ("два", 0.4, 0.8), ("три", 0.8, 1.2))
    dialogues = _dialogues(build_caption_ass([line], preset=FADE_PRESET))
    assert dialogues[0].count("\\fad(") == 1


def test_interior_word_events_carry_no_fad() -> None:
    line = _line(("раз", 0.0, 0.4), ("два", 0.4, 0.8), ("три", 0.8, 1.2))
    dialogues = _dialogues(build_caption_ass([line], preset=FADE_PRESET))
    for interior in dialogues[1:]:
        assert "\\fad(" not in interior


def test_each_caption_line_gets_its_own_entrance_fade() -> None:
    # The fade is per-LINE, not per-document: every line's first event fades, its interior
    # events do not — so a 3-line build has exactly 3 \fad, never a global single fade.
    line1 = _line(("раз", 0.0, 0.4), ("два", 0.4, 0.8))
    line2 = _line(("три", 1.0, 1.4), ("четыре", 1.4, 1.8))
    dialogues = _dialogues(build_caption_ass([line1, line2], preset=FADE_PRESET))
    assert "\\fad(" in dialogues[0]  # line 1 first event
    assert "\\fad(" not in dialogues[1]  # line 1 interior
    assert "\\fad(" in dialogues[2]  # line 2 first event (own fade, not the global first)
    assert "\\fad(" not in dialogues[3]  # line 2 interior


# --- tag ordering: \fad is the FIRST token in the first override block ---


def test_fad_is_first_tag_inside_first_override_block_pop_off() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))  # fitting line → scale_tag empty
    body = _line_body(line, 0, FADE_PRESET, fade_in_ms=FADE_MS)
    first_block = body.split(" ", 1)[0]
    assert first_block == f"{{\\fad({FADE_MS},0)\\c{DEFAULT_PRESET.active_colour}}}да"


def test_fade_composes_with_pop_first_block_has_fad_then_pop() -> None:
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))  # narrow → full pop
    preset = dataclasses.replace(DEFAULT_PRESET, pop=True, fade_in_ms=FADE_MS)
    body = _line_body(line, 0, preset, fade_in_ms=FADE_MS)
    first_block = body.split(" ", 1)[0]
    assert first_block == (
        f"{{\\fad({FADE_MS},0)\\fscx100\\fscy100"
        f"\\t(0,{POP_RISE_MS},\\fscx{POP_PEAK_PCT}\\fscy{POP_PEAK_PCT})"
        f"\\t({POP_RISE_MS},{POP_RISE_MS + POP_FALL_MS},\\fscx100\\fscy100)"
        f"\\c{DEFAULT_PRESET.active_colour}}}да"
    )


# --- composition with A2 lead: the first event still fades, at the lead-shifted start ---


def test_fade_composes_with_lead_first_event_still_carries_fad() -> None:
    preset = dataclasses.replace(DEFAULT_PRESET, lead_ms=70, fade_in_ms=FADE_MS)
    line = _line(("да", 0.9, 1.4), ("нет", 1.5, 2.0))
    dialogues = _dialogues(build_caption_ass([line], preset=preset))
    assert "\\fad(" in dialogues[0]
    assert dialogues[0].split(",")[1] == "0:00:00.83"  # 0.9 - 0.07, mirrors A2 lead test


# --- the window clamp: the fade always completes inside the first event ---


def test_fade_clamped_below_first_event_window() -> None:
    # A 60ms first-event window with a 500ms requested fade clamps to window_ms-1 = 59.
    line = _line(("ок", 1.0, 1.06))
    preset = dataclasses.replace(DEFAULT_PRESET, fade_in_ms=500)
    body = _dialogues(build_caption_ass([line], preset=preset))[0]
    assert "\\fad(59,0)" in body


def test_fade_clamped_when_requested_exactly_equals_window() -> None:
    # The contract is STRICTLY below the window: a fade equal to the window clamps to -1ms.
    line = _line(("ок", 1.0, 1.06))  # 60ms window
    preset = dataclasses.replace(DEFAULT_PRESET, fade_in_ms=60)
    body = _dialogues(build_caption_ass([line], preset=preset))[0]
    assert "\\fad(59,0)" in body


def test_negative_lead_or_fade_is_rejected_at_construction() -> None:
    # A negative ms offset is meaningless (it would silently no-op), so the invalid state
    # is unrepresentable — surfaced at the call site, not as a silently-wrong render.
    with pytest.raises(ValueError, match="fade_in_ms must be >= 0"):
        dataclasses.replace(DEFAULT_PRESET, fade_in_ms=-1)
    with pytest.raises(ValueError, match="lead_ms must be >= 0"):
        dataclasses.replace(DEFAULT_PRESET, lead_ms=-1)


def test_fade_in_ms_zero_via_line_body_is_unchanged() -> None:
    # _line_body with fade_in_ms=0 must equal the no-fade body (covers the gate).
    line = _line(("да", 1.0, 1.4), ("нет", 1.4, 2.0))
    assert _line_body(line, 0, FADE_PRESET, fade_in_ms=0) == _line_body(line, 0, DEFAULT_PRESET)


def test_new_field_round_trips_into_a_constructed_preset() -> None:
    preset = CaptionPreset(
        font_name="X",
        font_size=10,
        base_colour="&H00000000",
        active_colour="&H00FFFFFF",
        outline_colour="&H00000000",
        shadow_colour="&H00000000",
        outline_px=1,
        shadow_px=1,
        fade_in_ms=200,
    )
    assert preset.fade_in_ms == 200
