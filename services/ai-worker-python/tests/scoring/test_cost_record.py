"""Unit coverage for scoring/cost_record.py — pure fold, no paid call lost."""

import pytest

from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import ClipScore
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.cost_record import JobCostRecord, summarize_job_cost

_USAGE = {"prompt_tokens": 1_000_000, "completion_tokens": 0}


def _clip(model, *, used_video=True, usage=None):
    cand = CandidateClip("t", 0.0, 30.0, 50.0, 0.0, "txt")
    scored = ScoredClip(70.0, {}, 80, ["text"], model, _USAGE if usage is None else usage)
    return ClipScore(candidate=cand, scored=scored, used_video=used_video)


def test_two_models_two_subtotals():
    rec = summarize_job_cost([_clip("google/gemini-3.5-flash"), _clip("openai/gpt-5")])
    assert set(rec.by_model) == {"google/gemini-3.5-flash", "openai/gpt-5"}
    # gemini-3.5-flash: 1M prompt @0.30 = 0.30; gpt-5: 1M prompt @1.25 = 1.25
    assert rec.total_usd == pytest.approx(1.55)
    assert rec.by_model["google/gemini-3.5-flash"].calls == 1


def test_same_model_folds_into_one_subtotal():
    rec = summarize_job_cost([_clip("google/gemini-3.5-flash"), _clip("google/gemini-3.5-flash")])
    sub = rec.by_model["google/gemini-3.5-flash"]
    assert sub.calls == 2
    assert sub.prompt_tokens == 2_000_000
    assert sub.usd == pytest.approx(0.6)  # 2M prompt @0.30


def test_av_and_text_counts():
    rec = summarize_job_cost(
        [
            _clip("google/gemini-3.5-flash", used_video=True),
            _clip("google/gemini-3.5-flash", used_video=False),
        ],
        escalation_count=2,
    )
    assert rec.av_clip_count == 1 and rec.text_clip_count == 1
    assert rec.escalation_count == 2


def test_escalated_usages_add_a_call_without_losing_original():
    rec = summarize_job_cost(
        [_clip("google/gemini-3.5-flash")],
        escalated_usages=[
            ("google/gemini-2.5-pro", {"prompt_tokens": 1_000_000, "completion_tokens": 0})
        ],
    )
    # original gemini-3.5-flash call still present, plus the escalation call.
    assert rec.by_model["google/gemini-3.5-flash"].calls == 1
    assert rec.by_model["google/gemini-2.5-pro"].calls == 1
    # 0.30 (original @0.30) + 1.25 (gemini-2.5-pro 1M prompt @1.25) = 1.55
    assert rec.total_usd == pytest.approx(1.55)


def test_missing_usage_counted_in_mix():
    rec = summarize_job_cost([_clip("acme/unknown"), _clip("google/gemini-3.5-flash")])
    assert rec.missing_usage_count == 1
    assert rec.cost_source_mix["missing"] == 1
    assert rec.cost_source_mix["computed"] == 1


def test_empty_scores_zeroed():
    rec = summarize_job_cost([])
    assert dict(rec.by_model) == {}
    assert rec.total_usd == 0.0
    assert rec.av_clip_count == 0 and rec.text_clip_count == 0
    assert rec.missing_usage_count == 0 and dict(rec.cost_source_mix) == {}


def test_record_mappings_are_read_only():
    rec = summarize_job_cost([_clip("google/gemini-3.5-flash")])
    assert isinstance(rec, JobCostRecord)
    with pytest.raises(TypeError):
        rec.by_model["x"] = None  # type: ignore[index]
    with pytest.raises(TypeError):
        rec.cost_source_mix["y"] = 1  # type: ignore[index]
