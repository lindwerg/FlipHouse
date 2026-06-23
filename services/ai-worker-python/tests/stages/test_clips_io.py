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


def test_schema_version_bumped_to_v2() -> None:
    assert clips_io.CLIPS_SCHEMA_VERSION == 2


def test_dump_persists_scene_cut_times() -> None:
    result = CascadeResult(
        clips=(_sel(0),),
        cost_record=summarize_job_cost([]),
        scene_cut_times=(12.5, 48.0, 90.25),
    )
    payload = clips_io.dump_clips(result)
    assert payload["scene_cut_times"] == [12.5, 48.0, 90.25]
    assert clips_io.load_scene_cut_times(payload) == (12.5, 48.0, 90.25)


def test_load_scene_cut_times_defaults_to_empty_for_v1_payload() -> None:
    # A v1 clips.json (written before the field existed) has no scene_cut_times key —
    # the loader must default to () rather than KeyError (the versioned back-compat).
    legacy_v1 = {"schema_version": 1, "cost_usd_micros": 0, "clips": []}
    assert clips_io.load_scene_cut_times(legacy_v1) == ()
    # And the rest of the legacy payload still rebuilds.
    assert clips_io.load_selected_clips(legacy_v1) == []


def test_empty_result_dumps_empty_scene_cut_times() -> None:
    payload = clips_io.dump_clips(CascadeResult(clips=(), cost_record=summarize_job_cost([])))
    assert payload["scene_cut_times"] == []
    assert clips_io.load_scene_cut_times(payload) == ()


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
