"""Unit coverage for the final comparative re-rank pass (P2 clipping-mvp).

The LLM seam (``rank_fn``) is injected, so every path — a good permutation, each
malformed-reply branch, and the fail-open guards — is exercised with zero network.
"""

from dataclasses import dataclass

from fliphouse_worker.engine.rerank import (
    DEFAULT_RERANK_TOP_N,
    RERANK_SYSTEM_PROMPT,
    build_av_aware_rank_fn,
    build_rerank_prompt,
    parse_rerank_order,
    rerank_finalists,
)
from fliphouse_worker.llm.routes import Profile


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


@dataclass(frozen=True)
class _AvClip:
    candidate: _Cand
    scored: _Scored
    used_video: bool


def _clip(text: str, agg: float) -> _Clip:
    return _Clip(candidate=_Cand(text_excerpt=text), scored=_Scored(aggregate=agg))


def _av_clip(text: str, agg: float, used_video: bool) -> _AvClip:
    return _AvClip(
        candidate=_Cand(text_excerpt=text), scored=_Scored(aggregate=agg), used_video=used_video
    )


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


# ── RANK-3: A/V-aware rerank ────────────────────────────────────────────────


def test_prompt_marks_av_scored_clips():
    clips = [_av_clip("text-only clip", 70.0, False), _av_clip("a/v clip", 65.0, True)]
    prompt = build_rerank_prompt(clips)
    assert "[1]" in prompt and "[A/V-scored]" in prompt
    # the text-only line carries NO marker (so the judge knows which is which)
    line0 = prompt.split("\n\n")[1]
    assert "[0]" in line0 and "[A/V-scored]" not in line0


def test_prompt_no_marker_when_used_video_absent():
    # back-compat: a plain ClipScore (no used_video) renders the old text-only line.
    prompt = build_rerank_prompt([_clip("a", 80.0), _clip("b", 70.0)])
    assert "[A/V-scored]" not in prompt


def test_system_prompt_instructs_trusting_av_signal():
    assert "[A/V-scored]" in RERANK_SYSTEM_PROMPT


def test_av_aware_factory_routes_to_strong_judge():
    seen = {}

    def complete_fn(*, profile, system, user, temperature):
        seen["profile"] = profile
        seen["temperature"] = temperature
        return '{"order": [0]}'

    rank_fn = build_av_aware_rank_fn(complete_fn, av_aware=True)
    rank_fn("rank these")
    assert seen["profile"] is Profile.OFFER_MATCH  # the strong A/V-capable judge
    assert seen["temperature"] == 0.0


def test_text_only_tier_stays_on_cheap_route():
    seen = {}

    def complete_fn(*, profile, system, user, temperature):
        seen["profile"] = profile
        return '{"order": [0]}'

    build_av_aware_rank_fn(complete_fn, av_aware=False)("rank these")
    assert seen["profile"] is Profile.SCORING  # Бюджет stays text-only


def test_av_aware_rank_fn_drives_rerank_finalists():
    # End-to-end: the factory's rank_fn plugs into rerank_finalists and reorders.
    clips = [_av_clip(f"c{i}", 90.0 - i, i == 1) for i in range(3)]
    rank_fn = build_av_aware_rank_fn(
        lambda *, profile, system, user, temperature: '{"order": [2, 1, 0]}', av_aware=True
    )
    out = rerank_finalists(clips, rank_fn=rank_fn, top_n=3)
    assert [c.candidate.text_excerpt for c in out] == ["c2", "c1", "c0"]
