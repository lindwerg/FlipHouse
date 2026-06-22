"""PURE: build a libass ``.ass`` with native ``\\k`` karaoke word-highlight captions.

ONE ``[V4+ Styles]`` Style (Montserrat ExtraBold, bottom-centre, thick outline)
plus one ``Dialogue`` per grouped line. Each line uses native libass karaoke:
``{\\k<cs>}word`` advances a per-word timer in CENTISECONDS, and the active word
flips colour via an inline ``{\\c&H..&}`` override against the white base.

THE #1 ASS BUG — colour byte order. ASS colours are ``&HAABBGGRR``: alpha, then
BLUE, GREEN, RED — the REVERSE of CSS ``#RRGGBB`` — and ``AA=00`` is OPAQUE (not
transparent). A naive CSS-order literal is a different colour, and ``AA=FF`` is
fully transparent (invisible text). Both constants below are pinned by a golden.

``group_caption_lines`` packs 1–3 words per line, greedily breaking on a ~16-char
visible budget so lines stay short and dense (the captacity look). ``caption_y``
returns the ``MarginV`` (bottom margin) for the Style, lifting the band UP when a
source caption band was detected so our captions never overlap the burned-in
source subtitles.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .segments import CaptionWord

# Fontname MUST equal the family fc-list reports for the vendored static TTF
# (set via fonttools name records) — libass resolves the face through fontconfig.
FONT_NAME: str = "Montserrat ExtraBold"
FONT_SIZE: int = 140

# ASS colour literals — &HAABBGGRR (alpha-blue-green-red). AA=00 = OPAQUE.
BASE_COLOUR: str = "&H00FFFFFF"  # opaque white (resting word)
ACTIVE_COLOUR: str = "&H00303BFF"  # CSS #FF3B30 vermillion → BGR &H..303BFF (active word)
OUTLINE_COLOUR: str = "&H00000000"  # opaque black outline
SHADOW_COLOUR: str = "&H64000000"  # ~39% black shadow (AA=0x64)

OUTLINE_PX: int = 4
SHADOW_PX: int = 2
ALIGNMENT_BOTTOM_CENTRE: int = 2  # libass numpad alignment
MARGIN_LR: int = 40
DEFAULT_MARGIN_V: int = 210  # lower-third resting margin from the frame bottom

PLAY_RES_X: int = 1080
PLAY_RES_Y: int = 1920

MAX_WORDS_PER_LINE: int = 3
MAX_LINE_CHARS: int = 16
_GAP_ABOVE_SOURCE_BAND_PX: int = 24  # clearance kept between our text and a source band


@dataclass(frozen=True)
class CaptionLine:
    """A grouped caption line: 1–3 words sharing one ``Dialogue`` row."""

    start: float
    end: float
    words: tuple[CaptionWord, ...]


def escape_ass_text(text: str) -> str:
    """Neutralise ASS override metacharacters in caption TEXT (``\\`` then ``{`` ``}``).

    A literal ``{`` opens an override block and ``\\`` feeds a tag, so an
    unescaped one in user speech would corrupt the line. Backslash is escaped
    FIRST so the braces' escaping backslashes are not themselves doubled.
    """
    return text.replace("\\", "\\\\").replace("{", "\\{").replace("}", "\\}")


def group_caption_lines(words: Sequence[CaptionWord]) -> list[CaptionLine]:
    """Greedily pack words into lines of 1–3 words within a ~16 visible-char budget."""
    lines: list[CaptionLine] = []
    current: list[CaptionWord] = []
    char_count = 0
    for word in words:
        wlen = len(word.text)
        would_overflow = char_count + wlen > MAX_LINE_CHARS and current
        if len(current) >= MAX_WORDS_PER_LINE or would_overflow:
            lines.append(_finish_line(current))
            current = []
            char_count = 0
        current.append(word)
        char_count += wlen + 1  # +1 for the inter-word space
    if current:
        lines.append(_finish_line(current))
    return lines


def _finish_line(words: list[CaptionWord]) -> CaptionLine:
    """Close a line: its span is [first.start, last.end]."""
    return CaptionLine(start=words[0].start, end=words[-1].end, words=tuple(words))


def caption_y(source_caption_band: Mapping | None) -> int:
    """``MarginV`` (bottom margin px) for the Style, lifted above a source band.

    With no band → the resting lower-third margin. With a band, lift our text so
    its bottom clears the band's TOP edge: ``MarginV = PlayResY - band_top + gap``,
    clamped to be at least the default. A malformed band (missing ``y_top``) is
    ignored (fail-open → default).
    """
    if not isinstance(source_caption_band, Mapping):
        return DEFAULT_MARGIN_V
    y_top = source_caption_band.get("y_top")
    if not isinstance(y_top, (int, float)):
        return DEFAULT_MARGIN_V
    lifted = PLAY_RES_Y - int(y_top) + _GAP_ABOVE_SOURCE_BAND_PX
    return max(DEFAULT_MARGIN_V, lifted)


def _ass_timestamp(seconds: float) -> str:
    """Seconds → ASS ``H:MM:SS.cc`` (centisecond precision)."""
    cs_total = max(0, round(seconds * 100))
    cs = cs_total % 100
    s_total = cs_total // 100
    s = s_total % 60
    m = (s_total // 60) % 60
    h = s_total // 3600
    return f"{h}:{m:02d}:{s:02d}.{cs:02d}"


def _word_centiseconds(word: CaptionWord) -> int:
    """A word's ``\\k`` duration in centiseconds, floored at 1 (never 0 → no desync)."""
    return max(1, round((word.end - word.start) * 100))


def _build_style_line(margin_v: int) -> str:
    """The single V4+ Style row (pinned by the golden)."""
    return (
        "Style: Caption,"
        f"{FONT_NAME},{FONT_SIZE},"
        f"{BASE_COLOUR},{ACTIVE_COLOUR},{OUTLINE_COLOUR},{SHADOW_COLOUR},"
        f"-1,0,0,0,100,100,0,0,1,{OUTLINE_PX},{SHADOW_PX},"
        f"{ALIGNMENT_BOTTOM_CENTRE},{MARGIN_LR},{MARGIN_LR},{margin_v},1"
    )


def _build_dialogue(line: CaptionLine) -> str:
    """One ``Dialogue`` row: native ``\\k`` karaoke, active word flips to ACTIVE_COLOUR."""
    chunks: list[str] = []
    for word in line.words:
        cs = _word_centiseconds(word)
        text = escape_ass_text(word.text)
        # \k advances the karaoke timer; a separate \c override flips the swept
        # word to the active colour, then a trailing \c restores the white base.
        chunks.append(f"{{\\k{cs}}}{{\\c{ACTIVE_COLOUR}}}{text}{{\\c{BASE_COLOUR}}}")
    body = "".join(chunks)
    start = _ass_timestamp(line.start)
    end = _ass_timestamp(line.end)
    return f"Dialogue: 0,{start},{end},Caption,,0,0,0,,{body}"


def build_caption_ass(
    lines: Sequence[CaptionLine], source_caption_band: Mapping | None = None
) -> str:
    """Assemble the full UTF-8 ASS document (Script Info + one Style + Dialogues)."""
    margin_v = caption_y(source_caption_band)
    head = [
        "[Script Info]",
        "ScriptType: v4.00+",
        f"PlayResX: {PLAY_RES_X}",
        f"PlayResY: {PLAY_RES_Y}",
        "ScaledBorderAndShadow: yes",
        "WrapStyle: 2",
        "",
        "[V4+ Styles]",
        (
            "Format: Name,Fontname,Fontsize,PrimaryColour,SecondaryColour,"
            "OutlineColour,BackColour,Bold,Italic,Underline,StrikeOut,ScaleX,"
            "ScaleY,Spacing,Angle,BorderStyle,Outline,Shadow,Alignment,"
            "MarginL,MarginR,MarginV,Encoding"
        ),
        _build_style_line(margin_v),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    body = [_build_dialogue(line) for line in lines]
    return "\n".join([*head, *body]) + "\n"
