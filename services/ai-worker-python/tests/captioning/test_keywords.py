"""P3-A4: pure tests for the keyword selector seam (network-free, injected fakes)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from fliphouse_worker.captioning.ass import CaptionLine
from fliphouse_worker.captioning.keywords import (
    apply_line_keywords,
    build_gemini_keyword_selector,
    parse_keyword_response,
    stopword_keyword_selector,
)
from fliphouse_worker.captioning.segments import CaptionWord


def _line(*texts: str) -> CaptionLine:
    words = tuple(
        CaptionWord(text=t, start=float(i), end=float(i) + 1.0) for i, t in enumerate(texts)
    )
    return CaptionLine(start=0.0, end=float(len(texts)), words=words)


def _emphases(line: CaptionLine) -> list[bool]:
    return [w.emphasis for w in line.words]


# --- stopword_keyword_selector (pure dev default) ---


def test_stopword_selector_picks_longest_non_stopword() -> None:
    line = _line("это", "предприниматель", "сразу")  # "это" stopword-ish but <5; longest is idx 1
    assert stopword_keyword_selector([line]) == (1,)


def test_stopword_selector_returns_none_when_no_salient_token() -> None:
    assert stopword_keyword_selector([_line("да", "нет", "вот")]) == (None,)


def test_stopword_selector_tie_breaks_to_lowest_index() -> None:
    # two equal-length (6) non-stopwords → leftmost wins (deterministic).
    assert stopword_keyword_selector([_line("деньги", "оценка")]) == (0,)


def test_stopword_selector_casefolds_and_rejects_capitalised_stopword() -> None:
    # "Сейчас" is a stopword regardless of casing; "вложил" (>=5) is the only salient word.
    assert stopword_keyword_selector([_line("Сейчас", "вложил")]) == (1,)


# --- apply_line_keywords (stamping, density cap, fail-open) ---


def test_apply_keywords_all_none_returns_identity_objects() -> None:
    lines = [_line("деньги", "любят"), _line("счёт", "ведут")]
    out = apply_line_keywords(lines, lambda ls: [None] * len(ls))
    assert out is not lines  # a new list…
    assert out[0] is lines[0] and out[1] is lines[1]  # …of the SAME line objects (no replace)


def test_apply_keywords_stamps_exactly_one_word() -> None:
    line = _line("деньги", "любят", "счёт")
    out = apply_line_keywords([line], lambda ls: [2])
    assert _emphases(out[0]) == [False, False, True]


@pytest.mark.parametrize("bad", [[-1], [3], [True]])
def test_apply_keywords_rejects_out_of_range_or_bool_index(bad: list[object]) -> None:
    line = _line("деньги", "любят", "счёт")
    out = apply_line_keywords([line], lambda ls: bad)
    assert _emphases(out[0]) == [False, False, False]
    assert out[0] is line  # identity (no stamp)


def test_apply_keywords_length_mismatch_is_identity() -> None:
    lines = [_line("деньги"), _line("счёт")]
    out = apply_line_keywords(lines, lambda ls: [0])  # too short
    assert out is lines


def test_apply_keywords_raising_selector_is_identity() -> None:
    lines = [_line("деньги")]

    def boom(_ls: object) -> list[int | None]:
        raise RuntimeError("selector down")

    assert apply_line_keywords(lines, boom) is lines


def test_apply_keywords_density_caps_to_one_per_n_lines() -> None:
    # 5 stampable lines, density N=3 → lines 0 and 3 keep a keyword; 1,2,4 dropped.
    lines = [_line(f"слово{i}крупное") for i in range(5)]
    out = apply_line_keywords(lines, lambda ls: [0] * len(ls))
    kept = [i for i, line in enumerate(out) if any(w.emphasis for w in line.words)]
    assert kept == [0, 3]


# --- parse_keyword_response (never trusts the model) ---


def test_parse_maps_valid_rows() -> None:
    lines = [_line("a", "b"), _line("c", "d", "e")]
    data = {"lines": [{"line": 0, "keyword_index": 1}, {"line": 1, "keyword_index": 2}]}
    assert parse_keyword_response(data, lines) == (1, 2)


def test_parse_minus_one_and_out_of_word_range_become_none() -> None:
    lines = [_line("a", "b"), _line("c")]
    data = {"lines": [{"line": 0, "keyword_index": -1}, {"line": 1, "keyword_index": 9}]}
    assert parse_keyword_response(data, lines) == (None, None)


def test_parse_rejects_whole_response_on_out_of_range_line() -> None:
    lines = [_line("a"), _line("b")]
    data = {"lines": [{"line": 0, "keyword_index": 0}, {"line": 5, "keyword_index": 0}]}
    assert parse_keyword_response(data, lines) == (None, None)


def test_parse_rejects_whole_response_on_duplicate_or_shifted_line() -> None:
    lines = [_line("a"), _line("b")]
    dup = {"lines": [{"line": 0, "keyword_index": 0}, {"line": 0, "keyword_index": 0}]}
    shifted = {"lines": [{"line": 1, "keyword_index": 0}, {"line": 2, "keyword_index": 0}]}
    assert parse_keyword_response(dup, lines) == (None, None)
    assert parse_keyword_response(shifted, lines) == (None, None)


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"lines": "x"},
        {"lines": [42]},
        {"lines": [{"line": "x", "keyword_index": 0}]},  # non-int line → global reject
        {"lines": [{"line": True, "keyword_index": 0}]},  # bool line → global reject
        [1, 2],
        "nope",
    ],
)
def test_parse_bad_shape_is_all_none(data: Any) -> None:
    lines = [_line("a"), _line("b")]
    assert parse_keyword_response(data, lines) == (None, None)


# --- build_gemini_keyword_selector (faked complete_json, NO network) ---


@dataclass
class _FakeResult:
    data: dict[str, Any]


def test_gemini_selector_parses_a_canned_result() -> None:
    lines = [_line("деньги", "любят"), _line("счёт")]

    def fake(*, system: str, user: str) -> _FakeResult:
        assert "line 0:" in user and "line 1:" in user  # 0-based numbered prompt
        return _FakeResult(
            data={"lines": [{"line": 0, "keyword_index": 0}, {"line": 1, "keyword_index": -1}]}
        )

    assert build_gemini_keyword_selector(fake)(lines) == (0, None)


def test_gemini_selector_fails_open_on_raise_wronglen_baddata_and_no_data() -> None:
    lines = [_line("деньги"), _line("счёт")]
    none2 = (None, None)

    def raises(*, system: str, user: str) -> _FakeResult:
        raise RuntimeError("402")

    def bad_shape(*, system: str, user: str) -> _FakeResult:
        return _FakeResult(data={"lines": "garbage"})

    class _NoData:
        pass

    assert build_gemini_keyword_selector(raises)(lines) == none2
    assert build_gemini_keyword_selector(bad_shape)(lines) == none2
    # .data missing → AttributeError swallowed by the L1 try/except.
    assert build_gemini_keyword_selector(lambda **_: _NoData())(lines) == none2


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
