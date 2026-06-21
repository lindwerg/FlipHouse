"""clips.json dump/load symmetry (the score↔reframe internal contract)."""

from __future__ import annotations

import pytest

from fliphouse_worker.engine.cascade import CascadeResult, SelectedClip
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.cost_record import summarize_job_cost
from fliphouse_worker.stages import clips_io


def _sel(rank: int, *, agg: float = 80.0) -> SelectedClip:
    return SelectedClip(
        candidate=CandidateClip(
            title=f"clip {rank}",
            start_time=10.0,
            end_time=40.0,
            llm_score=70.0,
            dsp_prior=0.5,
            text_excerpt="excerpt",
        ),
        scored=ScoredClip(
            aggregate=agg,
            sub_scores={"hook": 80, "payoff": 70},
            confidence=4,
            modalities_used=["text"],
            model_used="gemini-3.5-flash",
            raw_usage={"total_tokens": 12},
        ),
        rank=rank,
        used_video=True,
    )


def test_dump_then_load_round_trips() -> None:
    result = CascadeResult(clips=(_sel(0), _sel(1, agg=60.0)), cost_record=summarize_job_cost([]))
    payload = clips_io.dump_clips(result)
    assert payload["schema_version"] == clips_io.CLIPS_SCHEMA_VERSION
    assert payload["cost_usd_micros"] == 0

    rebuilt = clips_io.load_selected_clips(payload)
    assert [c.rank for c in rebuilt] == [0, 1]
    assert rebuilt[0].candidate.title == "clip 0"
    assert rebuilt[0].scored.aggregate == 80.0
    assert rebuilt[1].scored.sub_scores == {"hook": 80, "payoff": 70}
    assert rebuilt[0].used_video is True


def test_dump_empty_result() -> None:
    payload = clips_io.dump_clips(CascadeResult(clips=(), cost_record=summarize_job_cost([])))
    assert payload["clips"] == []
    assert clips_io.load_selected_clips(payload) == []


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
