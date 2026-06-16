"""Unit coverage for engine/recall.py — Stage A recall with deterministic fake LLM."""

import json

import pytest

from fliphouse_worker.dsp.audio_energy import Pause
from fliphouse_worker.dsp.audio_flags import AudioWindowFlags
from fliphouse_worker.dsp.local_signals import LocalSignals
from fliphouse_worker.dsp.scene_cuts import SceneCut
from fliphouse_worker.engine.recall import (
    RECALL_OVERSAMPLE,
    CandidateClip,
    _excerpt,
    _proximity,
    _relaxed_dedupe,
    dsp_prior_score,
    recall_candidates,
    rrf_rank,
    snap_to_pause,
)

CONTENT_JSON = '{"content_type": "interview", "density": "high"}'


class FakeLLM:
    """content-type prompt → CONTENT_JSON; highlight prompt → fixed highlights JSON."""

    def __init__(self, highlights):
        self._payload = json.dumps({"highlights": highlights})
        self.calls = []

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if "classify the content type" in prompt:
            return CONTENT_JSON
        return self._payload


def _signals(pauses=(), peaks=(), cuts=(), flags=()):
    return LocalSignals(
        pauses=tuple(pauses),
        energy_peaks_s=tuple(peaks),
        scene_cuts=tuple(cuts),
        audio_flags=tuple(flags),
    )


def _hl(title, start, end, score):
    return {
        "title": title,
        "start_time": start,
        "end_time": end,
        "score": score,
        "hook_sentence": "",
        "virality_reason": "",
    }


# ── snap_to_pause ──────────────────────────────────────────────────────────


def test_snap_to_pause_hits_nearest_within_tol():
    assert snap_to_pause(10.4, (Pause(9.8, 10.2),)) == pytest.approx(10.0)  # mid 10.0


def test_snap_to_pause_miss_returns_original():
    assert snap_to_pause(50.0, (Pause(9.8, 10.2),)) == 50.0


def test_snap_to_pause_empty_pauses():
    assert snap_to_pause(7.0, ()) == 7.0


# ── proximity / prior ────────────────────────────────────────────────────────


def test_proximity_empty_targets_zero():
    assert _proximity((), 0.0, 5.0) == 0.0


def test_proximity_inside_interval_is_one():
    assert _proximity((3.0,), 0.0, 5.0) == 1.0  # distance 0 → 1/(1+0)


def test_proximity_below_and_above_interval():
    assert _proximity((-1.0,), 0.0, 5.0) == pytest.approx(0.5)  # dist 1 → 1/(1+1)
    assert _proximity((7.0,), 0.0, 5.0) == pytest.approx(1 / 3)  # dist 2 → 1/(1+2)


def test_dsp_prior_energy_peak_in_window():
    p = dsp_prior_score(10.0, 20.0, _signals(peaks=(15.0,)))
    assert p == pytest.approx(0.4)  # energy term 1.0 × 0.4 weight, others 0


def test_dsp_prior_scene_cut_near_hook():
    p = dsp_prior_score(10.0, 20.0, _signals(cuts=(SceneCut(11.0, 30.0),)))
    assert p == pytest.approx(0.3)  # cut inside hook window → cut term 1.0 × 0.3


def test_dsp_prior_flag_overlap():
    flags = (
        AudioWindowFlags(
            t=12.0, speech_conf=0.1, music_conf=0.8, laughter_conf=0.2, applause_conf=0.0
        ),
    )
    p = dsp_prior_score(10.0, 20.0, _signals(flags=flags))
    assert p == pytest.approx(0.3 * 0.8)  # flag term = max(laughter, music) = 0.8


def test_dsp_prior_no_signals_is_zero():
    assert dsp_prior_score(10.0, 20.0, _signals()) == 0.0


# ── rrf_rank ─────────────────────────────────────────────────────────────────


def test_rrf_rank_orders_by_fused_score():
    items = [
        {"id": "a", "llm_score": 90, "dsp_prior": 0.1},
        {"id": "b", "llm_score": 50, "dsp_prior": 0.9},
        {"id": "c", "llm_score": 10, "dsp_prior": 0.0},
    ]
    ranked = rrf_rank(items, llm_key="llm_score", prior_key="dsp_prior")
    assert {r["id"] for r in ranked[:2]} == {"a", "b"}  # top of each ranking
    assert ranked[-1]["id"] == "c"  # bottom of both
    assert all("fused" in r for r in ranked)


def test_rrf_rank_single_item():
    ranked = rrf_rank(
        [{"llm_score": 5, "dsp_prior": 0.5}], llm_key="llm_score", prior_key="dsp_prior"
    )
    assert len(ranked) == 1


# ── _relaxed_dedupe ──────────────────────────────────────────────────────────


def test_relaxed_dedupe_keeps_partial_overlap_drops_heavy():
    items = [
        {"start_time": 0.0, "end_time": 10.0},  # kept
        {"start_time": 6.0, "end_time": 16.0},  # 40% overlap of its span → kept (< 0.70)
        {"start_time": 0.5, "end_time": 10.5},  # ~95% overlap → dropped
    ]
    kept = _relaxed_dedupe(items)
    assert len(kept) == 2


def test_relaxed_dedupe_drops_long_clip_containing_kept_short():
    items = [
        {"start_time": 0.0, "end_time": 20.0},  # short, kept first
        {"start_time": 0.0, "end_time": 180.0},  # long, fully contains the short → dropped
    ]
    kept = _relaxed_dedupe(items)
    assert len(kept) == 1 and kept[0]["end_time"] == 20.0


# ── _excerpt ─────────────────────────────────────────────────────────────────


def test_excerpt_joins_overlapping_segments():
    transcript = {
        "segments": [
            {"start": 0, "end": 5, "text": "  alpha "},
            {"start": 5, "end": 10, "text": "beta"},
            {"start": 20, "end": 25, "text": "gamma"},
        ]
    }
    assert _excerpt(transcript, 4.0, 11.0) == "alpha beta"


# ── recall_candidates ────────────────────────────────────────────────────────


def test_recall_candidates_empty_transcript():
    assert recall_candidates({"segments": []}, _signals(), llm_fn=FakeLLM([])) == ()


def test_recall_candidates_returns_candidate_clips():
    transcript = {
        "duration": 120.0,
        "segments": [{"start": i * 10, "end": i * 10 + 10, "text": f"seg{i}"} for i in range(12)],
    }
    llm = FakeLLM([_hl("A", 0, 30, 80), _hl("B", 40, 70, 60), _hl("C", 80, 110, 40)])
    cands = recall_candidates(transcript, _signals(peaks=(20.0,)), llm_fn=llm, k=3)
    assert len(cands) == 3
    assert all(isinstance(c, CandidateClip) for c in cands)
    assert any("classify the content type" in p for p in llm.calls)


def test_recall_candidates_oversamples_and_disables_inner_dedupe(monkeypatch):
    captured = {}

    def fake_get_highlights(transcript, num_clips, *, llm_fn, dedupe):
        captured["num_clips"] = num_clips
        captured["dedupe"] = dedupe
        return {"highlights": [_hl("A", 0, 30, 50)]}

    monkeypatch.setattr("fliphouse_worker.engine.recall.get_highlights", fake_get_highlights)
    transcript = {"duration": 600.0, "segments": [{"start": 0, "end": 60, "text": "x"}]}
    recall_candidates(transcript, _signals(), llm_fn=FakeLLM([]), k=5)
    assert captured["num_clips"] == 5 * RECALL_OVERSAMPLE  # recall casts a wide net
    assert captured["dedupe"] is False  # inner 0.50 dedupe bypassed (HIGH-3 fix)


def test_recall_candidates_snaps_boundary_to_pause():
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "long"}]}
    llm = FakeLLM([_hl("A", 9.6, 40.0, 70)])
    cands = recall_candidates(transcript, _signals(pauses=(Pause(9.8, 10.2),)), llm_fn=llm, k=1)
    assert cands[0].start_time == pytest.approx(10.0)  # snapped to pause midpoint


def test_recall_candidates_reverts_when_snap_collapses_span():
    # both bounds within tol of the same pause mid → would collapse → fall back to LLM bounds
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "long"}]}
    llm = FakeLLM([_hl("A", 10.0, 11.0, 70)])
    cands = recall_candidates(transcript, _signals(pauses=(Pause(10.3, 10.7),)), llm_fn=llm, k=1)
    assert cands[0].start_time == 10.0 and cands[0].end_time == 11.0


def test_recall_candidates_no_duration_skips_clamp():
    transcript = {"segments": [{"start": 0, "end": 30, "text": "x"}]}  # no "duration" key → 0.0
    llm = FakeLLM([_hl("A", 0, 30, 50)])
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, k=1)
    assert len(cands) == 1
