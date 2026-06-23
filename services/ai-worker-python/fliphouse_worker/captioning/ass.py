"""PURE: build a libass ``.ass`` with PER-WORD reveal captions (captacity look).

ONE ``[V4+ Styles]`` Style (Montserrat ExtraBold, bottom-centre, thick outline)
plus, for every grouped line, ONE ``Dialogue`` row PER WORD: each row shows the
whole line and paints exactly the word being spoken in ``ACTIVE_COLOUR`` while the
rest stay ``BASE_COLOUR``, and the row's Start/End is that word's own time window.
So the highlight jumps word-by-word in sync with speech — a real per-word reveal,
not a static phrase block. (The earlier ``\\k`` karaoke approach rendered statically
because an inline ``\\c`` override clobbered the timer; per-word events are robust
and need no karaoke colour machinery.) Words are joined with a single SPACE — the
source words are ``lstrip``-ed in ``segments.py``, so without it they would collide
(e.g. ``лишили$9млрд`` instead of ``лишили $9 млрд``).

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


def _build_style_line(margin_v: int) -> str:
    """The single V4+ Style row (pinned by the golden)."""
    return (
        "Style: Caption,"
        f"{FONT_NAME},{FONT_SIZE},"
        f"{BASE_COLOUR},{ACTIVE_COLOUR},{OUTLINE_COLOUR},{SHADOW_COLOUR},"
        f"-1,0,0,0,100,100,0,0,1,{OUTLINE_PX},{SHADOW_PX},"
        f"{ALIGNMENT_BOTTOM_CENTRE},{MARGIN_LR},{MARGIN_LR},{margin_v},1"
    )


def _line_body(line: CaptionLine, active_index: int) -> str:
    """The line's text with word ``active_index`` in ACTIVE_COLOUR, rest BASE_COLOUR.

    Words are SPACE-joined (source words are ``lstrip``-ed). Each word carries an
    explicit ``\\c`` so the snapshot is unambiguous for its event window.
    """
    parts: list[str] = []
    for j, word in enumerate(line.words):
        colour = ACTIVE_COLOUR if j == active_index else BASE_COLOUR
        parts.append(f"{{\\c{colour}}}{escape_ass_text(word.text)}")
    return " ".join(parts)


def _build_dialogues(line: CaptionLine) -> list[str]:
    """One ``Dialogue`` row PER WORD: the whole line, only the spoken word active.

    Word ``i``'s row spans ``[word_i.start, word_{i+1}.start)`` (the last word runs
    to its own end), so the highlight advances word-by-word in sync with speech and
    the line is gap-free across its words. A degenerate (non-positive) window is
    nudged to a minimum so libass never drops the row.
    """
    rows: list[str] = []
    n = len(line.words)
    for i, word in enumerate(line.words):
        seg_start = word.start
        seg_end = line.words[i + 1].start if i + 1 < n else word.end
        if seg_end <= seg_start:
            seg_end = max(word.end, seg_start + 0.01)
        body = _line_body(line, i)
        rows.append(
            f"Dialogue: 0,{_ass_timestamp(seg_start)},{_ass_timestamp(seg_end)},"
            f"Caption,,0,0,0,,{body}"
        )
    return rows


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
    body = [row for line in lines for row in _build_dialogues(line)]
    return "\n".join([*head, *body]) + "\n"
