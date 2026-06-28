"""P3-A0: CaptionPreset scaffold — DEFAULT_PRESET is byte-identical to the golden."""

from __future__ import annotations

import dataclasses

import pytest

from fliphouse_worker.captioning.ass import (
    ACTIVE_COLOUR,
    BASE_COLOUR,
    DEFAULT_PRESET,
    FONT_NAME,
    FONT_SIZE,
    OUTLINE_COLOUR,
    OUTLINE_PX,
    SHADOW_COLOUR,
    SHADOW_PX,
    CaptionLine,
    build_caption_ass,
)
from fliphouse_worker.captioning.preset import CaptionPreset
from fliphouse_worker.captioning.segments import CaptionWord


def _sample_lines() -> list[CaptionLine]:
    words = (
        CaptionWord(text="Видео", start=0.0, end=0.4),
        CaptionWord(text="на", start=0.4, end=0.6),
        CaptionWord(text="входе", start=0.6, end=1.0),
    )
    return [CaptionLine(start=0.0, end=1.0, words=words)]


def test_default_preset_equals_existing_constants() -> None:
    assert DEFAULT_PRESET == CaptionPreset(
        font_name=FONT_NAME,
        font_size=FONT_SIZE,
        base_colour=BASE_COLOUR,
        active_colour=ACTIVE_COLOUR,
        outline_colour=OUTLINE_COLOUR,
        shadow_colour=SHADOW_COLOUR,
        outline_px=OUTLINE_PX,
        shadow_px=SHADOW_PX,
    )


def test_default_preset_reproduces_pinned_golden_bytes() -> None:
    # Passing DEFAULT_PRESET explicitly must equal the implicit-default render,
    # and both must still carry the pinned Style row — zero live regression.
    lines = _sample_lines()
    implicit = build_caption_ass(lines)
    explicit = build_caption_ass(lines, preset=DEFAULT_PRESET)
    assert explicit == implicit
    expected_style = (
        "Style: Caption,Montserrat ExtraBold,140,"
        "&H00FFFFFF,&H00303BFF,&H00000000,&H64000000,"
        "-1,0,0,0,100,100,0,0,1,4,2,2,40,40,430,1"
    )
    assert expected_style in explicit


def test_preset_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_PRESET.font_size = 999  # type: ignore[misc]


def test_active_colour_field_moves_exactly_that_token() -> None:
    custom = "&H00112233"
    preset = dataclasses.replace(DEFAULT_PRESET, active_colour=custom)
    lines = _sample_lines()
    out = build_caption_ass(lines, preset=preset)
    # the new active colour appears (active word + Style SecondaryColour) and the
    # default vermillion no longer does.
    assert custom in out
    assert ACTIVE_COLOUR not in out


def test_base_colour_field_moves_exactly_that_token() -> None:
    custom = "&H00445566"
    preset = dataclasses.replace(DEFAULT_PRESET, base_colour=custom)
    out = build_caption_ass(_sample_lines(), preset=preset)
    assert custom in out
    assert BASE_COLOUR not in out


def test_font_and_border_fields_round_trip_into_style() -> None:
    preset = dataclasses.replace(
        DEFAULT_PRESET,
        font_name="Inter Black",
        font_size=120,
        outline_colour="&H00010203",
        shadow_colour="&H00040506",
        outline_px=6,
        shadow_px=3,
    )
    out = build_caption_ass(_sample_lines(), preset=preset)
    assert (
        "Style: Caption,Inter Black,120,"
        "&H00FFFFFF,&H00303BFF,&H00010203,&H00040506,"
        "-1,0,0,0,100,100,0,0,1,6,3,2,40,40,430,1"
    ) in out


def test_border_style_defaults_to_one() -> None:
    # P3-A6: the band knob is OFF by default → the BorderStyle column stays the literal 1.
    assert DEFAULT_PRESET.border_style == 1


@pytest.mark.parametrize("bad", [0, 2, 4, 5, -1])
def test_border_style_rejects_out_of_domain(bad: int) -> None:
    # Only {1, 3} are real libass capabilities; 4 in particular silently degrades to plain
    # outline on every build, so it is rejected at construction rather than shipped inert.
    with pytest.raises(ValueError, match="border_style"):
        dataclasses.replace(DEFAULT_PRESET, border_style=bad)


@pytest.mark.parametrize("good", [1, 3])
def test_border_style_accepts_real_capabilities(good: int) -> None:
    assert dataclasses.replace(DEFAULT_PRESET, border_style=good).border_style == good


def test_preset_field_set_is_exactly_the_intended_twelve() -> None:
    # Lock: _ALLOWED_BORDER_STYLES must stay a MODULE constant, never a 13th dataclass
    # field (a class-body annotated assignment would inject it and crash import).
    names = {f.name for f in dataclasses.fields(CaptionPreset)}
    assert names == {
        "font_name",
        "font_size",
        "base_colour",
        "active_colour",
        "outline_colour",
        "shadow_colour",
        "outline_px",
        "shadow_px",
        "lead_ms",
        "pop",
        "fade_in_ms",
        "border_style",
    }
    assert "_ALLOWED_BORDER_STYLES" not in names


def test_border_style_round_trips_into_style_field_sixteen() -> None:
    preset = dataclasses.replace(DEFAULT_PRESET, border_style=3)
    out = build_caption_ass(_sample_lines(), preset=preset)
    # field#16 flips 1→3; the outline/shadow tokens that follow it are unchanged.
    assert ",0,0,3,4,2,2," in out
    assert ",0,0,1,4,2,2," not in out
