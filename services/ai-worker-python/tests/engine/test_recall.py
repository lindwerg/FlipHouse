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
    refine_boundaries,
    rrf_rank,
    snap_to_pause,
)


def _words(*triples):
    return [{"word": w, "start": s, "end": e} for (w, s, e) in triples]


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

    def fake_get_highlights(transcript, num_clips, *, llm_fn, dedupe, highlight_fn=None):
        captured["num_clips"] = num_clips
        captured["dedupe"] = dedupe
        return {"highlights": [_hl("A", 0, 30, 50)]}

    monkeypatch.setattr("fliphouse_worker.engine.recall.get_highlights", fake_get_highlights)
    transcript = {"duration": 600.0, "segments": [{"start": 0, "end": 60, "text": "x"}]}
    recall_candidates(transcript, _signals(), llm_fn=FakeLLM([]), k=5)
    assert captured["num_clips"] == 5 * RECALL_OVERSAMPLE  # recall casts a wide net
    assert captured["dedupe"] is False  # inner 0.50 dedupe bypassed (HIGH-3 fix)


def test_recall_candidates_refines_start_to_speech_edge():
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "long"}]}
    llm = FakeLLM([_hl("A", 9.6, 40.0, 70)])
    cands = recall_candidates(transcript, _signals(pauses=(Pause(9.8, 10.2),)), llm_fn=llm, k=1)
    assert cands[0].start_time == pytest.approx(10.2 - 0.08)  # speech resume (pause end) − lead pad
    assert cands[0].end_time == pytest.approx(40.0)


def test_recall_candidates_threads_word_segments_for_boundary_snap():
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "x"}]}
    llm = FakeLLM([_hl("A", 0.0, 40.8, 70)])
    word_segments = [
        {
            "start": 0.0,
            "end": 60.0,
            "words": [
                {"word": "a", "start": 0.0, "end": 40.0},
                {"word": "b", "start": 41.0, "end": 60.0},
            ],
        }
    ]
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, word_segments=word_segments, k=1)
    assert cands[0].end_time == pytest.approx(40.0 + 0.20)  # speech stop + trail pad


# ── refine_boundaries ────────────────────────────────────────────────────────


def test_refine_start_snaps_to_speech_resume_minus_lead():
    words = _words(("a", 0.0, 5.0), ("b", 12.0, 30.0))  # gap 5→12 → resume@12
    start, _ = refine_boundaries(11.5, 60.0, words, (), duration=120.0)
    assert start == pytest.approx(12.0 - 0.08)


def test_refine_end_snaps_to_speech_stop_plus_trail():
    words = _words(("a", 0.0, 40.0), ("b", 41.0, 60.0))  # gap 40→41 → stop@40
    _, end = refine_boundaries(0.0, 40.8, words, (), duration=120.0)
    assert end == pytest.approx(40.0 + 0.20)


def test_refine_prefers_sentence_end_over_nearer_gap():
    words = _words(("word", 0.0, 59.8), ("done.", 60.0, 60.6), ("then", 62.0, 90.0))
    # pause stop at 60.5 is NEARER target 60.5 but mid-sentence; the sentence-end
    # stop at 60.6 ("done.") must still win.
    _, end = refine_boundaries(0.0, 60.5, words, (Pause(60.5, 60.55),), duration=120.0)
    assert end == pytest.approx(60.6 + 0.20)


def test_refine_no_candidate_in_window_leaves_bound():
    words = _words(("a", 0.0, 5.0), ("b", 90.0, 100.0))  # only far gaps
    assert refine_boundaries(40.0, 70.0, words, (), duration=120.0) == (40.0, 70.0)


def test_refine_reverts_end_when_snap_breaks_min_duration():
    words = _words(("a", 0.0, 0.4), ("b", 1.0, 1.5), ("c", 20.0, 20.5), ("d", 21.5, 22.0))
    start, end = refine_boundaries(0.0, 22.0, words, (), duration=120.0)
    assert start == pytest.approx(0.92)  # snapped start kept
    assert end == pytest.approx(22.0)  # END reverts (snap would shrink clip < MIN_CLIP_S)


def test_refine_no_op_without_words_or_pauses():
    assert refine_boundaries(10.0, 50.0, (), (), duration=120.0) == (10.0, 50.0)


def test_refine_clamps_to_duration():
    words = _words(("a", 0.0, 5.0), ("b", 6.0, 130.0))  # resume@6 within window of start
    _, end = refine_boundaries(5.8, 200.0, words, (), duration=120.0)
    assert end <= 120.0


def test_refine_recognizes_ru_sentence_end_with_trailing_quote():
    words = _words(("сказал", 0.0, 59.5), ("он?»", 59.6, 60.2), ("дальше", 62.0, 90.0))
    _, end = refine_boundaries(0.0, 60.5, words, (), duration=120.0)
    assert end == pytest.approx(60.2 + 0.20)  # "он?»" recognized as sentence end


def test_refine_reverts_start_when_end_revert_insufficient():
    # snapped start+end both shift forward; reverting END alone stays < MIN, but
    # reverting START to the LLM bound yields a valid clip → START reverts.
    words = _words(("a", 0.0, 0.3), ("b", 1.0, 1.5), ("c", 19.0, 19.8), ("d", 20.5, 40.0))
    start, end = refine_boundaries(0.0, 19.0, words, (), duration=120.0)
    assert start == pytest.approx(0.0)  # START reverted
    assert end == pytest.approx(20.0)  # snapped end kept


def test_refine_falls_back_to_llm_bounds_when_no_valid_snap():
    # clip far below MIN and no snap can reach it → both reverts fail → LLM bounds.
    words = _words(("a", 0.0, 0.3), ("b", 1.0, 1.5), ("c", 4.0, 4.5), ("d", 5.5, 9.0))
    assert refine_boundaries(0.0, 5.0, words, (), duration=120.0) == (0.0, 5.0)


def test_recall_candidates_no_duration_skips_clamp():
    transcript = {"segments": [{"start": 0, "end": 30, "text": "x"}]}  # no "duration" key → 0.0
    llm = FakeLLM([_hl("A", 0, 30, 50)])
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, k=1)
    assert len(cands) == 1
