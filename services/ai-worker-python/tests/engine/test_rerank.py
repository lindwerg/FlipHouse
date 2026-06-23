"""Unit coverage for the final comparative re-rank pass (P2 clipping-mvp).

The LLM seam (``rank_fn``) is injected, so every path — a good permutation, each
malformed-reply branch, and the fail-open guards — is exercised with zero network.
"""

from dataclasses import dataclass

from fliphouse_worker.engine.rerank import (
    DEFAULT_RERANK_TOP_N,
    RERANK_SYSTEM_PROMPT,
    build_rerank_prompt,
    parse_rerank_order,
    rerank_finalists,
)


@dataclass(frozen=True)
class _Cand:
    text_excerpt: str


@dataclass(frozen=True)
class _Scored:
    aggregate: float


@dataclass(frozen=True)
class _Clip:
    candidate: _Cand
    scored: _Scored


def _clip(text: str, agg: float) -> _Clip:
    return _Clip(candidate=_Cand(text_excerpt=text), scored=_Scored(aggregate=agg))


# ── prompt ────────────────────────────────────────────────────────────────────


def test_system_prompt_demands_a_strict_permutation_and_banger_bias():
    assert "разнос" in RERANK_SYSTEM_PROMPT.lower()
    assert "BANGER" in RERANK_SYSTEM_PROMPT
    assert '"order"' in RERANK_SYSTEM_PROMPT


def test_build_prompt_indexes_and_trims_excerpts():
    clips = [_clip("a" * 1000, 80.0), _clip("короткий клип", 60.0)]
    prompt = build_rerank_prompt(clips)
    assert "[0]" in prompt and "[1]" in prompt
    assert "score 80.0" in prompt
    assert "a" * 401 not in prompt  # excerpt capped


# ── parse_rerank_order ─────────────────────────────────────────────────────────


def test_parse_valid_permutation():
    assert parse_rerank_order('{"order": [2, 0, 1]}', 3) == [2, 0, 1]


def test_parse_strips_markdown_fence():
    assert parse_rerank_order('```json\n{"order": [1, 0]}\n```', 2) == [1, 0]


def test_parse_rejects_non_json():
    assert parse_rerank_order("not json at all", 3) is None


def test_parse_rejects_non_dict_json():
    assert parse_rerank_order("[0, 1, 2]", 3) is None


def test_parse_rejects_missing_or_wrong_length_order():
    assert parse_rerank_order('{"nope": [0, 1]}', 2) is None
    assert parse_rerank_order('{"order": [0, 1]}', 3) is None  # wrong length


def test_parse_rejects_non_int_and_bool_indices():
    assert parse_rerank_order('{"order": [0, "1"]}', 2) is None
    assert parse_rerank_order('{"order": [true, false]}', 2) is None  # bools are not indices


def test_parse_rejects_out_of_range_or_duplicate_indices():
    assert parse_rerank_order('{"order": [0, 5]}', 2) is None  # out of range
    assert parse_rerank_order('{"order": [0, 0]}', 2) is None  # duplicate


# ── rerank_finalists ───────────────────────────────────────────────────────────


def test_rerank_reorders_head_keeps_tail():
    clips = [_clip(f"c{i}", 90.0 - i) for i in range(3)]
    # ask to reverse the (3-clip) head.
    out = rerank_finalists(clips, rank_fn=lambda _p: '{"order": [2, 1, 0]}', top_n=3)
    assert [c.candidate.text_excerpt for c in out] == ["c2", "c1", "c0"]


def test_rerank_only_touches_top_n_tail_untouched():
    clips = [_clip(f"c{i}", 90.0 - i) for i in range(5)]
    out = rerank_finalists(clips, rank_fn=lambda _p: '{"order": [1, 0]}', top_n=2)
    assert [c.candidate.text_excerpt for c in out] == ["c1", "c0", "c2", "c3", "c4"]


def test_rerank_noop_for_fewer_than_two():
    clips = [_clip("only", 80.0)]
    called = []
    out = rerank_finalists(clips, rank_fn=lambda p: called.append(p) or "{}")
    assert out == clips
    assert called == []  # no LLM call for a single finalist


def test_rerank_fail_open_on_raising_rank_fn():
    clips = [_clip("a", 80.0), _clip("b", 70.0)]

    def boom(_prompt: str) -> str:
        raise RuntimeError("network down")

    assert rerank_finalists(clips, rank_fn=boom) == clips


def test_rerank_fail_open_on_unparseable_reply():
    clips = [_clip("a", 80.0), _clip("b", 70.0)]
    assert rerank_finalists(clips, rank_fn=lambda _p: "garbage") == clips


def test_default_top_n_is_exported_and_positive():
    assert DEFAULT_RERANK_TOP_N > 1
