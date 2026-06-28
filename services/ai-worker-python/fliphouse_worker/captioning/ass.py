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

``group_caption_lines`` packs 1–3 words per line, greedily breaking on an ~11-char
visible budget calibrated so a Montserrat-ExtraBold @140px line NEVER exceeds the
usable frame width (``PLAY_RES_X - 2*MARGIN_LR`` = 1000px) and libass never
force-wraps it (which would silently double the block height and shove the band
up). A single token wider than the budget still gets its own line and is
horizontally auto-scaled (``\\fscx``/``\\fscy``) so an over-long RU word
(``предприниматель``) shrinks to fit instead of clipping the 1080-wide frame.

``caption_y`` returns the ``MarginV`` (bottom margin) for the Style. The resting
band sits in the CROSS-PLATFORM safe zone — well ABOVE the bottom ~25% that
TikTok/Reels/Shorts occupy with like/comment/share, the caption bar and sound
attribution (≈370px on ads) — so burned-in captions are never occluded by the
platform's own UI cluster. It lifts the band further UP when a source caption band
is detected so our captions also never overlap burned-in source subtitles.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from .metrics import text_width_em
from .preset import CaptionPreset
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

# Platform bottom-UI safe zone. TikTok/Reels/Shorts cover the bottom ~25% of the
# frame with the like/comment/share/bookmark rail + caption bar + sound
# attribution — ≈320px organically, ≈370px on ads. Captions placed inside that
# band are OCCLUDED, so the resting MarginV must clear it with a gap. SAFE_BOTTOM_PX
# is the reserved cluster height; GAP keeps the caption a touch above it. The
# resulting band bottom (y = PlayResY - MarginV ≈ 1490) lands inside the documented
# cross-platform caption_band [1180, 1600] (safe_zones.py) and below frame centre,
# so it neither hits the bottom UI nor collides with an upper-third speaker crop.
SAFE_BOTTOM_PX: int = 370
_SAFE_BOTTOM_GAP_PX: int = 60
DEFAULT_MARGIN_V: int = SAFE_BOTTOM_PX + _SAFE_BOTTOM_GAP_PX  # 430 — clears the bottom UI

PLAY_RES_X: int = 1080
PLAY_RES_Y: int = 1920

MAX_WORDS_PER_LINE: int = 3
# Usable text width = frame minus the L/R margins. A line wider than this would be
# force-wrapped by libass (or clip the frame), so the char budget below is sized so
# a Montserrat-ExtraBold @FONT_SIZE line stays within it.
USABLE_WIDTH_PX: int = PLAY_RES_X - 2 * MARGIN_LR  # 1000
# Mean glyph advance for Montserrat ExtraBold as a fraction of the em (font size).
# Measured ≈0.62·em across the RU+Latin+digit set (wide caps balanced by narrow
# i/l); used to translate the pixel budget into a char budget and to size a single
# over-long token's autoscale. Approximate by design — the autoscale below is the
# exact safety net; this fraction only needs to be a safe upper bound on the mean.
_GLYPH_ADVANCE_EM: float = 0.62
# Chars that fit USABLE_WIDTH_PX at FONT_SIZE: 1000 / (140·0.62) ≈ 11. Pinned here
# (not 16) so a packed line NEVER force-wraps. floor() keeps it conservative.
MAX_LINE_CHARS: int = int(USABLE_WIDTH_PX / (FONT_SIZE * _GLYPH_ADVANCE_EM))
_GAP_ABOVE_SOURCE_BAND_PX: int = 24  # clearance kept between our text and a source band

# P3-C1 — anti-linger. MAX_WORD_HOLD_S caps how long a row may LINGER past the spoken
# word: a non-last word's row would otherwise run to the NEXT word's start, freezing its
# highlight through a mid-line pause. The cap floors at the word's own end, so a slow word
# is shown in full and only trailing silence is trimmed. GAP_SPLIT_S breaks a line when
# the inter-word gap exceeds it, so a real pause starts a fresh line (the pre-pause word
# then ends at its own word.end). Both sit ABOVE every pinned-golden value (max golden
# word window 1.0s, max golden grouping gap 0.5s), so both are no-ops on the goldens.
MAX_WORD_HOLD_S: float = 1.2
GAP_SPLIT_S: float = 0.8

# P3-A3 — active-word pop. With preset.pop the spoken word scales base→peak→base via
# two libass ``\t`` inside its own per-word Dialogue event (pure ASS overrides → ONE
# encode, SPD-1), then settles to base. Off in DEFAULT_PRESET (preset.pop defaults
# False → golden byte-identical).
POP_PEAK_PCT: int = 115  # nominal peak as % of the word's BASE scale (composes on autoscale)
POP_RISE_MS: int = 80  # attack: base→peak (event-relative ms)
POP_FALL_MS: int = 80  # settle: peak→base; rise+fall = 160ms total per pop
# Frame-width budget for the popped line. The peak is clamped per word — using the REAL
# font advances (metrics.text_width_em), NOT the Latin len·0.62 heuristic — so the true
# rendered width of "non-active words at base + active word at peak" never exceeds this.
# Bound = the 1080 frame minus an edge gutter that absorbs the scaled outline+shadow and
# anti-aliasing, so the popped glyph ink never reaches the literal frame edge. A word with
# no headroom (a wide line already filling the frame) yields peak ≤ base → no ``\t`` is
# emitted (graceful no-pop, fit wins). NOT the 1000px resting usable margin: a 160ms
# transient may briefly use the L/R margin band, it must only never clip the frame.
POP_EDGE_SAFETY_PX: int = 16
POP_FRAME_BUDGET_PX: int = PLAY_RES_X - 2 * POP_EDGE_SAFETY_PX  # 1048

# The flagship look as a CaptionPreset value. Built FROM the constants above so its
# rendered bytes are identical to the pre-preset production caption (golden-pinned).
# New P3 looks are new CaptionPreset values; DEFAULT_PRESET never changes the golden.
DEFAULT_PRESET: CaptionPreset = CaptionPreset(
    font_name=FONT_NAME,
    font_size=FONT_SIZE,
    base_colour=BASE_COLOUR,
    active_colour=ACTIVE_COLOUR,
    outline_colour=OUTLINE_COLOUR,
    shadow_colour=SHADOW_COLOUR,
    outline_px=OUTLINE_PX,
    shadow_px=SHADOW_PX,
)

# P3-A6 — contrast-band expressive looks. DEFAULT is the byte-identical baseline; the two
# band presets are BOTH libass BorderStyle=3 (the only real box style) so there is NO
# libass-version dependency and NO runtime capability gate. With bs=3 the ``outline_colour``
# field is REPURPOSED as the BOX FILL (ASS alpha INVERTED: 00=opaque, FF=transparent):
#   CONTRAST_BAND_BS3        — opaque near-black box (&H00101010), the production-safe band.
#   CONTRAST_BAND_TRANSLUCENT — same box at ~50% alpha (&H80101010); degrades to opaque
#                               (still legible) if a build ignores box alpha, never to "no band".
#   CONTRAST_OUTLINE         — no-box halo bump (border_style stays 1, ZERO new field).
# Box looks keep ``pop=False``: a bs=3 box is sized to the rendered text bbox, so composing
# it with the active-word pop would pulse the band once per word (see CAPTION_PRESETS guard).
CONTRAST_BAND_BS3: CaptionPreset = dataclasses.replace(
    DEFAULT_PRESET, border_style=3, outline_colour="&H00101010", outline_px=8, shadow_px=0
)
CONTRAST_BAND_TRANSLUCENT: CaptionPreset = dataclasses.replace(
    DEFAULT_PRESET, border_style=3, outline_colour="&H80101010", outline_px=8, shadow_px=0
)
CONTRAST_OUTLINE: CaptionPreset = dataclasses.replace(DEFAULT_PRESET, outline_px=6, shadow_px=3)
# Named looks a job may select (see reframe._select_caption_preset). Absent → DEFAULT.
CAPTION_PRESETS: dict[str, CaptionPreset] = {
    "default": DEFAULT_PRESET,
    "band": CONTRAST_BAND_BS3,
    "band_translucent": CONTRAST_BAND_TRANSLUCENT,
    "outline": CONTRAST_OUTLINE,
}


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


def estimate_line_width_px(text: str) -> float:
    """Approximate rendered width (px) of a caption line at FONT_SIZE.

    ``len`` × mean glyph advance (``FONT_SIZE·_GLYPH_ADVANCE_EM``). Used to size the
    autoscale safety net for an over-long single token; the char-budget packer keeps
    normal lines well inside ``USABLE_WIDTH_PX`` so this only ever fires on a lone
    word longer than the budget (e.g. ``предприниматель``)."""
    return len(text) * FONT_SIZE * _GLYPH_ADVANCE_EM


def _line_scale_pct(text: str) -> int:
    """Horizontal scale % so ``text`` fits ``USABLE_WIDTH_PX`` (100 when it already fits).

    A single token wider than the usable width gets a uniform ``\\fscx``/``\\fscy``
    shrink so it NEVER clips the 1080-wide frame — fit wins over punch for a rare
    20+ char token. ``int()`` floors the percentage so the scaled width can only be
    AT or UNDER the budget (rounding up could leave a 1px overflow). Floored at a
    still-readable 50% as a sanity guard for a pathological token. Normal lines fit
    → 100% (no override, golden-stable)."""
    width = estimate_line_width_px(text)
    if width <= USABLE_WIDTH_PX:
        return 100
    return max(50, int(USABLE_WIDTH_PX / width * 100))


def group_caption_lines(words: Sequence[CaptionWord]) -> list[CaptionLine]:
    """Greedily pack words into lines of 1–3 words within the visible-char budget.

    A line also breaks when the gap from the buffered word to the incoming one exceeds
    ``GAP_SPLIT_S`` (P3-C1): a real mid-line PAUSE starts a new line, so the pre-pause
    word becomes that line's last word and ends at its own ``word.end`` instead of
    lingering across the silence. Normal speech (sub-``GAP_SPLIT_S`` gaps) is unaffected.
    """
    lines: list[CaptionLine] = []
    current: list[CaptionWord] = []
    char_count = 0
    for word in words:
        wlen = len(word.text)
        would_overflow = char_count + wlen > MAX_LINE_CHARS and current
        gap_break = bool(current) and word.start - current[-1].end > GAP_SPLIT_S
        if len(current) >= MAX_WORDS_PER_LINE or would_overflow or gap_break:
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

    With no band → the resting margin (``DEFAULT_MARGIN_V``), which already clears the
    platform bottom-UI safe zone. With a band, lift our text so its bottom clears the
    band's TOP edge: ``MarginV = PlayResY - band_top + gap``, clamped to be at least
    the default. A malformed band (missing ``y_top``) is ignored (fail-open → default).
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


def _build_style_line(margin_v: int, preset: CaptionPreset) -> str:
    """The single V4+ Style row (DEFAULT_PRESET reproduces the pinned golden)."""
    return (
        "Style: Caption,"
        f"{preset.font_name},{preset.font_size},"
        f"{preset.base_colour},{preset.active_colour},"
        f"{preset.outline_colour},{preset.shadow_colour},"
        f"-1,0,0,0,100,100,0,0,{preset.border_style},{preset.outline_px},{preset.shadow_px},"
        f"{ALIGNMENT_BOTTOM_CENTRE},{MARGIN_LR},{MARGIN_LR},{margin_v},1"
    )


def _pop_peak_pct(visible: str, active_text: str, base: int) -> int:
    """Active-word peak ``\\fscx``/``\\fscy`` (% of original) for the pop, clamped per word
    against the REAL font metrics so the popped line can never clip the frame.

    Only the active word grows (others stay at ``base``), so the true popped width is
    ``others·base + active·peak``. ``peak`` is the largest value (≤ the nominal
    ``base·POP_PEAK_PCT``) keeping that width within ``POP_FRAME_BUDGET_PX``. ``floor``
    keeps it at-or-under budget (rounding up could re-introduce a 1px clip). Never below
    ``base`` (no inverse pop); an empty/edge word returns ``base`` so the caller emits no
    ``\\t`` — a graceful no-pop where fit wins.

    (The trailing inter-word space sits inside the active word's tag scope, so it too
    renders at ``peak`` — the formula counts it at ``base``, under-counting the popped
    width by ``space_em·FONT_SIZE·(peak-base)/100`` ≈ 6px worst-case, comfortably inside
    the 2·POP_EDGE_SAFETY_PX=32px frame gutter.)
    """
    active_em = text_width_em(active_text)
    if active_em <= 0:
        return base
    others_em = max(0.0, text_width_em(visible) - active_em)
    others_px = others_em * FONT_SIZE * base / 100.0
    headroom_px = POP_FRAME_BUDGET_PX - others_px
    peak_cap = int(headroom_px * 100.0 / (active_em * FONT_SIZE))
    nominal = base * POP_PEAK_PCT // 100
    return max(base, min(nominal, peak_cap))


def _resolve_word_colour(
    j: int, active_index: int, word: CaptionWord, preset: CaptionPreset
) -> str:
    """Per-WORD, per-EVENT caption colour. Precedence active > keyword > base.

    P3-A4. Active is checked FIRST so the keyword word still renders ``active_colour`` in the
    one event where it is spoken. ``keyword_colour is None`` on DEFAULT_PRESET → this returns
    EXACTLY ``active_colour if j==active_index else base_colour`` (the historical ternary at
    ass.py:338/349) regardless of ``word.emphasis`` → the pinned golden is byte-identical even
    when every word carries ``emphasis=True``. Used in BOTH the pop and no-pop branches so the
    precedence can never diverge between them.
    """
    if j == active_index:
        return preset.active_colour
    if preset.keyword_colour is not None and word.emphasis:
        return preset.keyword_colour
    return preset.base_colour


def _line_body(
    line: CaptionLine, active_index: int, preset: CaptionPreset, *, fade_in_ms: int = 0
) -> str:
    """The line's text with word ``active_index`` in active colour, rest base colour.

    Words are SPACE-joined (source words are ``lstrip``-ed). Each word carries an
    explicit ``\\c`` so the snapshot is unambiguous for its event window. When the
    line is wider than the usable frame width (only a lone over-budget token can be),
    the FIRST word's override also carries an ``\\fscx``/``\\fscy`` shrink so the line
    fits instead of clipping the frame; libass applies a leading scale tag to the
    whole line, so it does not need repeating per word.

    With ``preset.pop`` ON the spoken word additionally pulses base→peak→base via two
    event-relative ``\\t`` (the event Start IS this word's adjusted start, so the pop
    fires once when the word lights up and settles back). Because inline ``\\fscx``
    PERSISTS forward within a Dialogue, EVERY word must re-assert its base scale or the
    animated scale would bleed into later words in the same event — so the pop branch
    emits ``\\fscx{base}\\fscy{base}`` on every word, the active word prefixed with the
    two ``\\t``. ``peak`` is clamped per word (real-metric) so it never clips the frame;
    when there is no headroom (``peak <= base``) no ``\\t`` is emitted (graceful no-pop).
    With pop OFF this is the historical body verbatim → DEFAULT_PRESET stays golden.

    P3-A5 — ``fade_in_ms`` (>0 only on a line's FIRST event; the caller passes 0 for
    interior events so the line never re-fades = no strobe) prepends a single
    ``\\fad(fade_in_ms,0)`` to the FIRST word's override. ``\\fad`` is line-scoped, so its
    position is functionally irrelevant; it is pinned FIRST to keep the golden
    deterministic and orthogonal to the scale/pop tags it precedes. fade_in_ms<=0 emits
    nothing → byte-identical to the no-fade body.
    """
    visible = " ".join(w.text for w in line.words)
    scale = _line_scale_pct(visible)
    fade_tag = f"\\fad({fade_in_ms},0)" if fade_in_ms > 0 else ""
    if not preset.pop:
        scale_tag = "" if scale >= 100 else f"\\fscx{scale}\\fscy{scale}"
        parts: list[str] = []
        for j, word in enumerate(line.words):
            colour = _resolve_word_colour(j, active_index, word, preset)
            prefix = (fade_tag + scale_tag) if j == 0 else ""
            parts.append(f"{{{prefix}\\c{colour}}}{escape_ass_text(word.text)}")
        return " ".join(parts)

    base = max(scale, 1)  # _line_scale_pct floors at 50; guard keeps the ratio well-defined
    peak = _pop_peak_pct(visible, line.words[active_index].text, base)
    base_reset = f"\\fscx{base}\\fscy{base}"
    settle = POP_RISE_MS + POP_FALL_MS
    pop_parts: list[str] = []
    for j, word in enumerate(line.words):
        colour = _resolve_word_colour(j, active_index, word, preset)
        anim = ""
        if j == active_index and peak > base:
            anim = (
                f"\\t(0,{POP_RISE_MS},\\fscx{peak}\\fscy{peak})"
                f"\\t({POP_RISE_MS},{settle},\\fscx{base}\\fscy{base})"
            )
        lead = fade_tag if j == 0 else ""
        pop_parts.append(f"{{{lead}{base_reset}{anim}\\c{colour}}}{escape_ass_text(word.text)}")
    return " ".join(pop_parts)


def _first_event_fade_ms(seg_start: float, seg_end: float, requested_ms: int) -> int:
    """Entrance-fade ms for a line's FIRST event, clamped strictly below its on-screen window.

    ``\\fad`` does not extend the row's duration, so a fade longer than the event window
    would be clipped mid-entrance. The window is measured in the SAME centiseconds libass
    sees (``_ass_timestamp`` rounds to cs), and the result is held one ms under it so the
    fade always completes before the row cuts. ``requested_ms <= 0`` (the default —
    ``preset.fade_in_ms == 0`` when no fade is configured) returns 0 → no ``\\fad`` →
    golden-stable. (Interior events never reach here: the caller only invokes this for the
    line's first event and hard-passes 0 to ``_line_body`` for the rest.)
    """
    if requested_ms <= 0:
        return 0
    window_ms = (round(seg_end * 100) - round(seg_start * 100)) * 10
    return max(0, min(requested_ms, window_ms - 1))


def _lead_adjusted_starts(line: CaptionLine, lead_s: float) -> list[float]:
    """Per-word highlight starts pulled ``lead_s`` earlier, clamped ≥0 and monotonic.

    Each start is ``max(0, word.start - lead_s)`` but never earlier than the previous
    word's adjusted start, so the per-word windows stay ordered and non-overlapping
    (exactly one active word). With ``lead_s == 0`` and monotonic input this is the
    historical ``word.start`` for every word — golden-stable.
    """
    starts: list[float] = []
    for i, word in enumerate(line.words):
        s = max(0.0, word.start - lead_s)
        if i > 0:
            s = max(s, starts[i - 1])
        starts.append(s)
    return starts


def _build_dialogues(line: CaptionLine, preset: CaptionPreset) -> list[str]:
    """One ``Dialogue`` row PER WORD: the whole line, only the spoken word active.

    Word ``i``'s row spans ``[start_i, start_{i+1})`` (the last word runs to its own
    end), where ``start`` is the read-ahead-adjusted, monotonic per-word start, so the
    highlight advances word-by-word in sync with speech and the line is gap-free across
    its words. A degenerate (non-positive) window is nudged to a minimum so libass
    never drops the row.
    """
    rows: list[str] = []
    n = len(line.words)
    starts = _lead_adjusted_starts(line, preset.lead_ms / 1000.0)
    for i, word in enumerate(line.words):
        seg_start = starts[i]
        seg_end = starts[i + 1] if i + 1 < n else word.end
        if seg_end <= seg_start:
            seg_end = max(word.end, seg_start + 0.01)
        # P3-C1: cap how long a row LINGERS — a non-last word would otherwise hold through
        # the silence up to the NEXT word's start. The floor is the word's OWN end, so a
        # genuinely slow word (incl. the last word, whose seg_end IS word.end) is shown in
        # FULL — never truncated mid-speech — and only trailing silence is trimmed to
        # MAX_WORD_HOLD_S. After the nudge and BEFORE the fade clamp (so the fade window is
        # measured against the capped span); the floor (>= word.end, > seg_start) keeps the
        # row valid — this can only shrink trailing silence, never invert the window.
        seg_end = min(seg_end, max(word.end, seg_start + MAX_WORD_HOLD_S))
        # P3-A5: the entrance fade rides ONLY the line's first event (i == 0); interior
        # events get 0 so the line never re-fades per word (no strobe). The window is read
        # from the lead-adjusted, nudged seg times, so fade composes with lead automatically.
        fade = _first_event_fade_ms(seg_start, seg_end, preset.fade_in_ms) if i == 0 else 0
        body = _line_body(line, i, preset, fade_in_ms=fade)
        rows.append(
            f"Dialogue: 0,{_ass_timestamp(seg_start)},{_ass_timestamp(seg_end)},"
            f"Caption,,0,0,0,,{body}"
        )
    return rows


def build_caption_ass(
    lines: Sequence[CaptionLine],
    source_caption_band: Mapping | None = None,
    *,
    preset: CaptionPreset = DEFAULT_PRESET,
) -> str:
    """Assemble the full UTF-8 ASS document (Script Info + one Style + Dialogues).

    ``preset`` selects the look; ``DEFAULT_PRESET`` renders the golden byte-for-byte.
    """
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
        _build_style_line(margin_v, preset),
        "",
        "[Events]",
        "Format: Layer,Start,End,Style,Name,MarginL,MarginR,MarginV,Effect,Text",
    ]
    body = [row for line in lines for row in _build_dialogues(line, preset)]
    return "\n".join([*head, *body]) + "\n"
