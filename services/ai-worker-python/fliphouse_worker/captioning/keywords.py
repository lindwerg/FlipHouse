"""PURE: pick the <=1 salient keyword word per caption LINE (the second-colour accent).

P3-A4. A ``KeywordIndexSelector`` runs over ALL of a clip's GROUPED lines at once (so the
live Gemini look is ONE batched call per clip, and the ``<=1 per line`` / density invariants
are enforceable post-grouping). ``apply_line_keywords`` stamps ``CaptionWord.emphasis=True``
on at most one word per line, density-capped to <=1 per N lines, immutably and FAIL-OPEN: any
selector raise / length-mismatch / out-of-range index degrades to the plain (un-emphasised)
lines, so a paid clip never fails.

The DEFAULT selector is the pure ``stopword_keyword_selector`` (no network, no env read) — a
known-weak RU salience proxy, DEV/TEST ONLY (founder lock). The LIVE look is the Gemini seam
(``build_gemini_keyword_selector``), wired only behind the ``KEYWORD_LLM_ENABLED`` gate in the
stage layer. This module imports NO network/cv2/IO and NO LLM client — the Gemini bridge
closes over an injected ``complete_json`` callable, faked in tests.
"""

from __future__ import annotations

import dataclasses
import unicodedata
from collections.abc import Callable, Mapping, Sequence

from .ass import CaptionLine

# A clip's grouped lines -> at most one chosen word index per line (None = no keyword).
KeywordIndexSelector = Callable[[Sequence[CaptionLine]], Sequence["int | None"]]

# Sparsity: at most one keyword per this many consecutive lines (mirrors the A8 emoji cap) —
# keeps the second colour a semantic accent, not noise.
_KEYWORD_DENSITY_N = 3
# A heuristic keyword must clear this CASE-FOLDED length (a weak RU salience proxy, DEV only).
_MIN_KEYWORD_LEN = 5

# Lowercased stopword sets (pure stdlib). A salient word is a non-stopword clearing the length
# floor; these filter the obvious function words so the dev heuristic does not pick "который".
_RU_STOPWORDS: frozenset[str] = frozenset(
    {
        "который",
        "которые",
        "потому",
        "когда",
        "после",
        "очень",
        "просто",
        "сейчас",
        "может",
        "также",
        "чтобы",
        "этого",
        "этому",
        "будет",
        "более",
        "около",
        "перед",
        "через",
        "между",
    }
)
_EN_STOPWORDS: frozenset[str] = frozenset(
    {"which", "because", "their", "there", "would", "could", "should", "about", "these", "those"}
)

KEYWORD_SYSTEM_PROMPT = (
    "You highlight ONE emphatic keyword per short-video caption line. The user message lists "
    "the clip's caption lines, each numbered with a 0-based `line` index, and each line's words "
    "numbered with a 0-based local `keyword_index`. For EACH line pick AT MOST ONE most-emphatic "
    "word (a hook noun/number/verb — e.g. деньги/ноль/всё — NOT a function word) and return its "
    "0-based local index, or -1 for none. Be SPARSE: at most one keyword per ~3 lines across the "
    'whole clip. Return STRICT JSON only: {"lines":[{"line":0,"keyword_index":2}, ...]} with '
    "exactly one row per input line, indices 0-based."
)


def _normalise_token(text: str) -> str:
    """NFC + casefold + ё→е + strip caption punctuation so casing/ASR variants classify alike."""
    folded = unicodedata.normalize("NFC", text).casefold().replace("ё", "е")
    return folded.strip(" .,!?:;…—«»\"'()")


def stopword_keyword_selector(lines: Sequence[CaptionLine]) -> tuple[int | None, ...]:
    """DEV/TEST default (founder-locked, pure). Per line: the LEFTMOST-LONGEST non-stopword
    token whose normalised length is >= ``_MIN_KEYWORD_LEN``, else None.

    Deterministic: iterate left→right keeping the first token of strictly-greater length, so on
    a length tie the lowest index wins. Stopword + length tests run on the normalised form. A
    known-weak RU salience proxy — DEV ONLY.
    """
    out: list[int | None] = []
    for line in lines:
        best_idx: int | None = None
        best_len = _MIN_KEYWORD_LEN - 1
        for i, word in enumerate(line.words):
            norm = _normalise_token(word.text)
            if norm in _RU_STOPWORDS or norm in _EN_STOPWORDS:
                continue
            if len(norm) > best_len:
                best_len, best_idx = len(norm), i
        out.append(best_idx)
    return tuple(out)


def _enforce_density(chosen: list[int | None]) -> list[int | None]:
    """Keep a stamped index only if >= ``_KEYWORD_DENSITY_N`` lines since the last kept one;
    otherwise drop to None. Deterministic, left-to-right, pure."""
    out: list[int | None] = []
    since = _KEYWORD_DENSITY_N  # allow an immediate first stamp
    for idx in chosen:
        if idx is not None and since >= _KEYWORD_DENSITY_N:
            out.append(idx)
            since = 1
        else:
            out.append(None)
            since += 1
    return out


def apply_line_keywords(
    lines: list[CaptionLine], selector: KeywordIndexSelector
) -> list[CaptionLine]:
    """Stamp ``emphasis=True`` on at most one word per line, density-capped, immutably.

    FAIL-OPEN: a selector that raises, or returns a wrong-length sequence, yields the input
    lines unchanged (identity → byte-identical). Per line: a non-int / bool / out-of-range
    index → no emphasis. Returns the SAME object for unstamped lines; one
    ``dataclasses.replace`` carrying exactly one emphasised word otherwise.
    """
    try:
        chosen = list(selector(lines))
    except Exception:  # noqa: BLE001 — fail-open: a bad selector never blocks a paid clip
        return lines
    if len(chosen) != len(lines):
        return lines
    normalised: list[int | None] = []
    for line, idx in zip(lines, chosen, strict=True):
        valid = isinstance(idx, int) and not isinstance(idx, bool) and 0 <= idx < len(line.words)
        normalised.append(idx if valid else None)
    normalised = _enforce_density(normalised)
    out: list[CaptionLine] = []
    for line, idx in zip(lines, normalised, strict=True):
        if idx is None:
            out.append(line)
            continue
        words = tuple(
            dataclasses.replace(w, emphasis=True) if k == idx else w
            for k, w in enumerate(line.words)
        )
        out.append(dataclasses.replace(line, words=words))
    return out


def parse_keyword_response(
    raw_data: Mapping, lines: Sequence[CaptionLine]
) -> tuple[int | None, ...]:
    """Map ``{"lines":[{"line":int,"keyword_index":int}, ...]}`` → a per-line tuple.

    NEVER trusts the model. GLOBAL consistency (mirrors ``parse_rerank_order``): if ANY ``line``
    value is out of ``range(len(lines))`` OR repeats, REJECT the WHOLE response → all-None (a
    1-based / shifted reply fails CLOSED rather than mis-painting an adjacent word). Per row:
    ``-1`` / out-of-word-range / bad type → None for that line. Bad outer shape → all-None.
    """
    n = len(lines)
    none_tuple = tuple(None for _ in range(n))
    if not isinstance(raw_data, Mapping):
        return none_tuple
    rows = raw_data.get("lines")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return none_tuple
    per_line: dict[int, int] = {}
    seen: set[int] = set()
    for row in rows:
        if not isinstance(row, Mapping):
            return none_tuple
        line_no = row.get("line")
        if not isinstance(line_no, int) or isinstance(line_no, bool):
            return none_tuple
        if line_no < 0 or line_no >= n or line_no in seen:
            return none_tuple  # shifted/duplicate → fail CLOSED on the whole response
        seen.add(line_no)
        kw = row.get("keyword_index")
        per_line[line_no] = kw if isinstance(kw, int) and not isinstance(kw, bool) else -1
    result: list[int | None] = []
    for i, line in enumerate(lines):
        idx = per_line.get(i, -1)
        result.append(idx if 0 <= idx < len(line.words) else None)
    return tuple(result)


def _render_lines_prompt(lines: Sequence[CaptionLine]) -> str:
    """The user message: each line numbered 0-based, its words tagged with 0-based local index."""
    blocks: list[str] = []
    for i, line in enumerate(lines):
        words = " ".join(f"[{k}]{w.text}" for k, w in enumerate(line.words))
        blocks.append(f"line {i}: {words}")
    return "\n".join(blocks)


def build_gemini_keyword_selector(
    complete_json_fn: Callable[..., object],
) -> KeywordIndexSelector:
    """Bridge closing over an injected ``complete_json``-shaped callable (this module imports no
    LLM client — same discipline as ``rerank.build_av_aware_rank_fn``).

    The selector wraps the ENTIRE chain (call + ``.data`` access + parse) in ONE try/except →
    all-None, so L1 is self-sufficient: a 402/timeout/non-JSON/truncation raise, or a missing
    ``.data``, degrades to no keywords (the plain caption still ships).
    """

    def _select(lines: Sequence[CaptionLine]) -> tuple[int | None, ...]:
        try:
            result = complete_json_fn(
                system=KEYWORD_SYSTEM_PROMPT, user=_render_lines_prompt(lines)
            )
            return parse_keyword_response(result.data, lines)
        except Exception:  # noqa: BLE001 — fail-open: a down/garbled Gemini never blocks a clip
            return tuple(None for _ in lines)

    return _select
