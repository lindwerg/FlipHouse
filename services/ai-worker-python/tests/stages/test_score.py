"""Unit tests for the score stage handler (the cascade itself faked)."""

from __future__ import annotations

import json

import pytest

from fliphouse_worker.engine.cascade import CascadeResult, SelectedClip
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import DegradationCounts
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.cost_record import summarize_job_cost
from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.score import score_handler

from ._fakes import FakeR2, make_request


def _sel(rank: int) -> SelectedClip:
    return SelectedClip(
        candidate=CandidateClip("c", 10.0, 40.0, 70.0, 0.5, "x"),
        scored=ScoredClip(80.0, {"hook": 80}, 4, ["text"], "gemini", {"total_tokens": 5}),
        rank=rank,
        used_video=True,
    )


def _req(r2: FakeR2) -> dict:
    return make_request(
        "score",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "transcript": "asr-h0/cascade_transcript.json",
            "word_segments": "asr-h0/word_segments.json",
        },
    )


def _deps(r2: FakeR2, result: CascadeResult) -> StageDeps:
    return StageDeps(r2=r2, score_clips=lambda t, src, params: result)


def test_score_serializes_ranked_clips_and_cost() -> None:
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "asr-h0/cascade_transcript.json": b'{"segments":[]}',
            "asr-h0/word_segments.json": b"[]",
        }
    )
    result = CascadeResult(clips=(_sel(0), _sel(1)), cost_record=summarize_job_cost([]))
    out = score_handler(_req(r2), _deps(r2, result))

    assert [a["key"] for a in out["outputs"]] == ["score-h1/clips.json"]
    assert out["metrics"]["clip_count"] == 2
    assert out["metrics"]["cost_usd_micros"] == 0
    payload = json.loads(r2.uploaded["score-h1/clips.json"])
    assert [c["rank"] for c in payload["clips"]] == [0, 1]


def test_score_serializes_scene_cut_times_into_clips_json() -> None:
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "asr-h0/cascade_transcript.json": b'{"segments":[]}',
            "asr-h0/word_segments.json": b"[]",
        }
    )
    result = CascadeResult(
        clips=(_sel(0),),
        cost_record=summarize_job_cost([]),
        scene_cut_times=(18.0, 64.5),
    )
    score_handler(_req(r2), _deps(r2, result))
    payload = json.loads(r2.uploaded["score-h1/clips.json"])
    assert payload["schema_version"] == 2
    assert payload["scene_cut_times"] == [18.0, 64.5]  # threaded score→clips.json→reframe


def test_score_surfaces_degradation_counts_in_metrics() -> None:
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "asr-h0/cascade_transcript.json": b'{"segments":[]}',
            "asr-h0/word_segments.json": b"[]",
        }
    )
    deg = DegradationCounts(
        av_succeeded=3, av_failed_fellback=1, modalities_dropped=2, budget_skipped=4
    )
    result = CascadeResult(clips=(_sel(0),), cost_record=summarize_job_cost([]), degradation=deg)
    out = score_handler(_req(r2), _deps(r2, result))
    metrics = out["metrics"]
    assert metrics["av_succeeded"] == 3
    assert metrics["av_failed_fellback"] == 1
    assert metrics["modalities_dropped"] == 2
    assert metrics["budget_skipped"] == 4


def test_score_passes_source_path_and_threads_word_segments_into_params() -> None:
    ws_json = b'[{"start":0,"end":1,"words":[{"word":"hi","start":0,"end":1}]}]'
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "asr-h0/cascade_transcript.json": b'{"segments":[]}',
            "asr-h0/word_segments.json": ws_json,
        }
    )
    seen = {}

    def score_clips(transcript: dict, src: str, params: dict) -> CascadeResult:
        seen["src"], seen["params"], seen["transcript"] = src, params, transcript
        return CascadeResult(clips=(), cost_record=summarize_job_cost([]))

    req = make_request(
        "score",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "transcript": "asr-h0/cascade_transcript.json",
            "word_segments": "asr-h0/word_segments.json",
        },
        params={"k": 5},
    )
    out = score_handler(req, StageDeps(r2=r2, score_clips=score_clips))
    assert seen["src"].endswith("source.mp4")
    # k is preserved AND the parsed word_segments are injected for boundary snapping.
    assert seen["params"]["k"] == 5
    assert seen["params"]["word_segments"] == [
        {"start": 0, "end": 1, "words": [{"word": "hi", "start": 0, "end": 1}]}
    ]
    assert seen["transcript"] == {"segments": []}
    assert out["metrics"]["clip_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
