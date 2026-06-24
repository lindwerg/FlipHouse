"""Unit coverage for engine/recall.py — Stage A recall with deterministic fake LLM."""

import json

import pytest

from fliphouse_worker.dsp.audio_energy import Pause
from fliphouse_worker.dsp.audio_flags import AudioWindowFlags
from fliphouse_worker.dsp.local_signals import LocalSignals
from fliphouse_worker.dsp.scene_cuts import SceneCut
from fliphouse_worker.engine.punctuation import annotate_sentence_ends
from fliphouse_worker.engine.recall import (
    MAX_CLIP_S,
    MAX_EXTEND_END_S,
    MIN_CLIP_S,
    RECALL_OVERSAMPLE,
    SENTENCE_COMPLETE_BUDGET_S,
    TRAIL_PAD_S,
    CandidateClip,
    _excerpt,
    _extend_to_sentence_completion,
    _flatten_words,
    _gap_candidates,
    _pick_end_edge,
    _proximity,
    _relaxed_dedupe,
    _stop_windows,
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


# ── RU discourse / restored-punctuation boundary candidates ──────────────────


def test_flatten_words_annotates_sentence_end_from_pause():
    word_segments = [
        {"words": [{"word": "закончил", "start": 0.0, "end": 1.0}]},
        {"words": [{"word": "Потом", "start": 1.6, "end": 2.0}]},  # pause 0.6 + Capitalized
    ]
    flat = _flatten_words(word_segments)
    assert flat[0]["sent_end"] is True  # restored sentence end with no punctuation
    assert flat[1]["sent_end"] is False


def test_gap_candidates_stop_prefers_restored_sentence_end():
    # "вот и всё" (STOP marker) ends a thought; the stop candidate at its end is preferred.
    words = annotate_sentence_ends(
        _words(("вот", 0.0, 0.3), ("и", 0.35, 0.5), ("всё", 0.55, 0.9), ("дальше", 2.0, 3.0))
    )
    _, stop = _gap_candidates(words)
    # the gap is 0.9 → 2.0 (>= GAP_MIN_S); stop lands on "всё" end and is sentence-preferred
    assert stop == [(pytest.approx(0.9), True)]


def test_gap_candidates_resume_fresh_on_discourse_opener():
    # speech resumes on "итак" (START marker) → resume candidate flagged fresh-start.
    words = annotate_sentence_ends(
        _words(("слово", 0.0, 1.0), ("итак", 2.0, 2.5), ("поехали", 2.6, 3.5))
    )
    resume, _ = _gap_candidates(words)
    assert resume == [(pytest.approx(2.0), True)]  # resume on the discourse opener, fresh


def test_refine_end_snaps_to_discourse_stop_marker_without_punctuation():
    # No terminal punctuation anywhere; the tail must still land on "всё" (STOP marker).
    words = annotate_sentence_ends(
        _words(
            ("я", 0.0, 20.0),
            ("сказал", 20.1, 39.5),
            ("вот", 39.6, 39.8),
            ("и", 39.85, 39.95),
            ("всё", 40.0, 40.5),
            ("потом", 42.0, 60.0),
        )
    )
    _, end = refine_boundaries(0.0, 40.8, words, (), duration=120.0)
    assert end == pytest.approx(40.5 + 0.20)  # speech stop at "всё" end + trail pad


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
    # "c." is a real sentence end, so a backward snap to it is ALLOWED — but it
    # would shrink the clip below MIN_CLIP_S, so the END reverts to the LLM bound.
    words = _words(("a", 0.0, 0.4), ("b", 1.0, 1.5), ("c.", 14.0, 14.5), ("d", 15.5, 16.5))
    start, end = refine_boundaries(0.0, 16.0, words, (), duration=120.0)
    assert start == pytest.approx(0.92)  # snapped start kept
    assert end == pytest.approx(16.0)  # END reverts (snap would shrink clip < MIN_CLIP_S=15)


def test_refine_accepts_15s_window_without_reverting():
    # A ~15s window (the viral floor, MIN_CLIP_S=15) snaps cleanly and is KEPT —
    # neither side reverts, since the snapped duration stays >= MIN_CLIP_S.
    words = _words(("a", 0.0, 0.3), ("b", 1.0, 16.0), ("c", 17.0, 30.0))
    start, end = refine_boundaries(0.0, 16.0, words, (), duration=120.0)
    assert start == pytest.approx(0.92)  # resume@1.0 - lead pad, snapped start kept
    assert end == pytest.approx(16.0 + 0.20)  # stop@16.0 + trail pad, snapped end kept
    assert end - start >= 15.0  # survives the MIN_CLIP_S=15 floor


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
    words = _words(("a", 0.0, 0.3), ("b", 1.0, 1.5), ("c", 14.0, 14.8), ("d", 15.8, 40.0))
    start, end = refine_boundaries(0.0, 14.0, words, (), duration=120.0)
    assert start == pytest.approx(0.0)  # START reverted
    assert end == pytest.approx(15.0)  # snapped end kept


def test_refine_falls_back_to_llm_bounds_when_no_valid_snap():
    # clip far below MIN and no snap can reach it → both reverts fail → LLM bounds.
    words = _words(("a", 0.0, 0.3), ("b", 1.0, 1.5), ("c", 4.0, 4.5), ("d", 5.5, 9.0))
    assert refine_boundaries(0.0, 5.0, words, (), duration=120.0) == (0.0, 5.0)


def test_recall_candidates_no_duration_skips_clamp():
    transcript = {"segments": [{"start": 0, "end": 30, "text": "x"}]}  # no "duration" key → 0.0
    llm = FakeLLM([_hl("A", 0, 30, 50)])
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, k=1)
    assert len(cands) == 1


# ── _stop_windows ────────────────────────────────────────────────────────────


def test_stop_windows_from_word_gaps_and_pauses():
    words = annotate_sentence_ends(
        _words(("готово.", 0.0, 40.0), ("дальше", 41.0, 60.0))  # gap 1.0, "готово." sent-end
    )
    windows = _stop_windows(words, (Pause(70.0, 71.0),))
    # word-gap window (stop=40, silence_end=41, sentence-end=True) + pause window.
    assert (pytest.approx(40.0), pytest.approx(41.0), True) in windows
    assert (pytest.approx(70.0), pytest.approx(71.0), False) in windows


# ── _pick_end_edge — forward-biased sentence completion ──────────────────────


def test_pick_end_edge_extends_forward_to_sentence_end():
    # A sentence-end stop 3s AHEAD of the LLM end is chosen (extend to finish).
    windows = [(43.0, 44.0, True)]  # stop ahead of target, a real sentence end
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) == pytest.approx(43.0)


def test_pick_end_edge_prefers_nearest_forward_sentence_end():
    windows = [(43.0, 43.5, True), (47.0, 47.5, True)]  # two ahead → nearest wins
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) == pytest.approx(43.0)


def test_pick_end_edge_forward_extension_capped_by_max_extend():
    # The only forward sentence-end is beyond MAX_EXTEND_END_S → no forward extend;
    # with no other eligible stop, the LLM end is kept (None).
    windows = [(40.0 + MAX_EXTEND_END_S + 0.5, 90.0, True)]
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) is None


def test_pick_end_edge_forward_extension_capped_by_ceiling():
    # A forward sentence-end past the MAX_CLIP_S ceiling is rejected as a forward
    # target; no other candidate → keep the LLM end.
    windows = [(44.0, 45.0, True)]
    assert _pick_end_edge(windows, 40.0, ceiling=43.0) is None  # 44.0 > ceiling


def test_pick_end_edge_backward_sentence_end_allowed():
    # No forward target; a backward SENTENCE-END within MAX_SHIFT_END_S is fine.
    windows = [(39.0, 39.5, True)]  # 1s back, but a real sentence end
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) == pytest.approx(39.0)


def test_pick_end_edge_backward_into_trailing_silence_allowed():
    # Backward, NOT a sentence end, but the target sits in the stop's trailing
    # silence [39, 41] → snapping back only trims dead air, never truncates speech.
    windows = [(39.0, 41.0, False)]
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) == pytest.approx(39.0)


def test_pick_end_edge_rejects_backward_mid_sentence_truncation():
    # Backward mid-sentence stop whose trailing silence ENDS before the target
    # (words were spoken after it) → snapping back would truncate → rejected → None.
    windows = [(38.0, 38.5, False)]  # silence_end 38.5 < target 40 → speech after
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) is None


def test_pick_end_edge_forward_sentence_end_beats_backward_candidate():
    # A nearer backward sentence-end exists, but a forward sentence-end must still win.
    windows = [(39.5, 40.0, True), (42.0, 42.5, True)]
    assert _pick_end_edge(windows, 40.0, ceiling=200.0) == pytest.approx(42.0)


def test_pick_end_edge_no_windows_keeps_llm_end():
    assert _pick_end_edge([], 40.0, ceiling=200.0) is None


# ── refine_boundaries — end forward-extension (the founder fix) ───────────────


def test_refine_end_extends_forward_to_complete_the_sentence():
    # LLM end (40.8) lands a few seconds BEFORE the sentence-end at "всё" (44.0).
    # The tail must EXTEND forward to finish the thought, not snap back to a breath.
    words = annotate_sentence_ends(
        _words(
            ("я", 0.0, 20.0),
            ("говорю", 20.1, 40.0),  # mid-sentence breath after this word (gap 40→40.65)
            ("вот", 40.65, 43.0),  # gap 0.65 < LONG_PAUSE, lowercase → NOT a sentence end
            ("и", 43.05, 43.2),
            ("всё", 43.3, 44.0),  # STOP marker "вот и всё" → sentence end here
            ("потом", 46.0, 60.0),  # later resume (gap 44→46 closes the клип-able thought)
        )
    )
    _, end = refine_boundaries(0.0, 40.3, words, (), duration=120.0)
    assert end == pytest.approx(44.0 + 0.20)  # extended forward to "всё" + trail pad


def test_refine_end_does_not_snap_backward_onto_mid_sentence_breath():
    # The only stop is a mid-sentence breath BEFORE the LLM end with speech after it
    # → must keep the (clamped) LLM end rather than truncate the thought.
    words = _words(
        ("a", 0.0, 30.0),
        ("b", 30.65, 31.0),  # gap 0.65 (< LONG_PAUSE, mid-sentence breath), speech continues
        ("c", 31.0, 60.0),  # words spoken well past the LLM end
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=120.0)
    assert end == pytest.approx(40.0)  # LLM end kept; no backward truncating snap


def test_refine_end_extension_capped_by_max_clip_duration():
    # A forward sentence-end exists but would push the clip past MAX_CLIP_S from the
    # start → the ceiling rejects it and the LLM end is kept (no overrun).
    far = MAX_CLIP_S + 3.0
    words = annotate_sentence_ends(
        _words(
            ("a", 0.0, MAX_CLIP_S - 1.0), ("done.", far, far + 1.0), ("next", far + 3.0, far + 4.0)
        )
    )
    _, end = refine_boundaries(0.0, MAX_CLIP_S - 0.5, words, (), duration=far + 10.0)
    assert end <= MAX_CLIP_S  # never extends past the Shorts hard cap


def test_refine_start_logic_unchanged_by_end_bias():
    # Guard: the START still snaps to the speech-resume minus the lead pad exactly
    # as before — the forward END bias must not touch start behavior.
    words = _words(("a", 0.0, 5.0), ("b", 12.0, 80.0))  # gap 5→12 → resume@12
    start, _ = refine_boundaries(11.5, 60.0, words, (), duration=120.0)
    assert start == pytest.approx(12.0 - 0.08)


def test_refine_end_fail_open_when_no_words_or_pauses():
    # No candidates at all → both bounds returned unchanged (fail-open to LLM).
    assert refine_boundaries(10.0, 50.0, (), (), duration=120.0) == (10.0, 50.0)


# ── punct_fn / align_fn seams (phrase-complete boundaries) ───────────────────


def test_flatten_words_forwards_punct_fn_to_annotate():
    # A punct_fn flagging a word with NO pause cue still produces sent_end=True via
    # _flatten_words → annotate_sentence_ends (the live segmenter path forwards this).
    word_segments = [
        {"words": [{"word": "первое", "start": 0.0, "end": 1.0}]},
        {"words": [{"word": "второе", "start": 1.05, "end": 2.0}]},  # tiny gap, no cue
    ]

    def punct_fn(words):
        return [w["word"] == "первое" for w in words]

    flat = _flatten_words(word_segments, punct_fn=punct_fn)
    assert flat[0]["sent_end"] is True  # model-confirmed, no pause needed
    assert flat[1]["sent_end"] is False


def test_flatten_words_default_punct_fn_none_unchanged():
    word_segments = [
        {"words": [{"word": "закончил", "start": 0.0, "end": 1.0}]},
        {"words": [{"word": "Потом", "start": 1.6, "end": 2.0}]},  # pause + Capitalized
    ]
    base = _flatten_words(word_segments)
    seamed = _flatten_words(word_segments, punct_fn=None)
    assert [w["sent_end"] for w in base] == [w["sent_end"] for w in seamed]


def test_recall_candidates_punct_fn_ends_window_on_model_sentence_terminus():
    # No punctuation, no long pause → without the model the tail snaps to a bare
    # breath. A punct_fn marking "всё" (40.5s end) as a terminus makes the END
    # forward-extend to that sentence end instead.
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "x"}]}
    llm = FakeLLM([_hl("A", 0.0, 40.3, 70)])
    word_segments = [
        {
            "words": [
                {"word": "я", "start": 0.0, "end": 20.0},
                {"word": "сказал", "start": 20.1, "end": 39.5},
                {"word": "всё", "start": 40.0, "end": 40.5},  # model sentence end
                {"word": "потом", "start": 43.0, "end": 60.0},  # next thought (gap 2.5)
            ]
        }
    ]

    def punct_fn(words):
        return [w["word"] == "всё" for w in words]

    cands = recall_candidates(
        transcript, _signals(), llm_fn=llm, word_segments=word_segments, punct_fn=punct_fn, k=1
    )
    assert cands[0].end_time == pytest.approx(40.5 + 0.20)  # forward-extended to "всё" + trail


def test_recall_candidates_align_fn_anchors_bounds_to_phrase_words():
    # A verbatim-phrase align_fn resolves the highlight's start/end phrases to word
    # timestamps; refine_boundaries then only pads/clamps around those anchors.
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "x"}]}
    hl = _hl("A", 2.0, 90.0, 70)  # LLM floats deliberately off; phrases pin the truth
    hl["start_phrase"] = "итак начнём"
    hl["end_phrase"] = "вот и всё"
    llm = FakeLLM([hl])
    word_segments = [
        {
            "words": [
                {"word": "итак", "start": 10.0, "end": 10.5},
                {"word": "начнём", "start": 10.6, "end": 11.0},
                {"word": "вот", "start": 39.0, "end": 39.3},
                {"word": "и", "start": 39.35, "end": 39.5},
                {"word": "всё", "start": 39.6, "end": 40.0},
                {"word": "потом", "start": 42.5, "end": 60.0},  # gap so 40.0 is a stop
            ]
        }
    ]

    def align_fn(phrase, words, near_t):
        spans = {"итак начнём": (0, 1), "вот и всё": (2, 4)}
        return spans.get(phrase)

    cands = recall_candidates(
        transcript, _signals(), llm_fn=llm, word_segments=word_segments, align_fn=align_fn, k=1
    )
    # Pre-refine start anchored to words[0].start=10.0, end to words[4].end=40.0.
    # No speech-resume gap precedes word 0, so refine keeps the anchored start (no
    # lead pad); the end lands on the "вот и всё" sentence terminus (40.0) + trail.
    # Both are driven by the phrase anchors, NOT the off LLM floats (2.0 / 90.0).
    assert cands[0].start_time == pytest.approx(10.0)
    assert cands[0].end_time == pytest.approx(40.0 + 0.20)


def test_punct_fn_forward_extend_beats_backward_breath_regression():
    # REGRESSION GUARD: with a backward breath BEFORE the target and a model-flagged
    # sentence end AHEAD of it, the END must forward-extend to the sentence end
    # (finish the thought) rather than snap back onto the breath (truncate it).
    words = annotate_sentence_ends(
        _words(
            ("a", 0.0, 30.0),
            ("b", 30.7, 38.0),  # backward breath at 30.0 (gap 0.7), mid-thought
            ("конец", 38.1, 40.0),  # model sentence end AHEAD of target
            ("дальше", 40.65, 60.0),  # gap 0.65 → stop window exists at "конец" end
        ),
        punct_fn=lambda ws: [w["word"] == "конец" for w in ws],
    )
    # Target 36.0 sits AFTER the backward breath (30.0) and BEFORE the terminus (40.0).
    _, end = refine_boundaries(0.0, 36.0, words, (), duration=120.0)
    assert end == pytest.approx(40.0 + 0.20)  # extended forward to the model sentence end


def test_punct_fn_forward_end_clamped_by_max_clip_regression():
    # REGRESSION GUARD: a model sentence end beyond the MAX_CLIP_S ceiling is rejected
    # as a forward target; the clip reverts in-band and never overruns the hard cap.
    far = MAX_CLIP_S + 3.0
    words = annotate_sentence_ends(
        _words(
            ("a", 0.0, MAX_CLIP_S - 1.0),
            ("конец", far, far + 1.0),  # model terminus, but past the cap
            ("next", far + 3.0, far + 4.0),
        ),
        punct_fn=lambda ws: [w["word"] == "конец" for w in ws],
    )
    _, end = refine_boundaries(0.0, MAX_CLIP_S - 0.5, words, (), duration=far + 10.0)
    assert end <= MAX_CLIP_S  # the ceiling/clamp survives the truer-but-farther terminus


def test_recall_candidates_align_fn_absent_uses_float_bounds():
    # With no align_fn (and phrases present), behavior falls back to today's
    # float→refine path — phrases are ignored, the LLM floats drive the bounds.
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "x"}]}
    hl = _hl("A", 0.0, 50.0, 70)
    hl["start_phrase"] = "итак"
    hl["end_phrase"] = "всё"
    llm = FakeLLM([hl])
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, k=1)
    # No word_segments, no pauses, no align_fn → refine is a no-op, floats kept.
    assert cands[0].start_time == pytest.approx(0.0)
    assert cands[0].end_time == pytest.approx(50.0)


# ── sentence-completion forward-extension (the c1/c5 mid-thought fix) ─────────
# These pin the ROOT-CAUSE fix: when the anchored END lands mid-sentence (e.g. on
# "кто" / "поэтому"), a sentence terminus that exists LATER but carries NO gap after
# it (the next word follows immediately) is unreachable by the gap-keyed stop-window
# logic. _extend_to_sentence_completion scans the WORD LIST directly and pushes the
# END forward to that terminus within a generous budget.


def test_extend_to_sentence_completion_reaches_punct_terminus_without_a_gap():
    # The terminus word "поэтому." carries terminal punctuation but the next word
    # follows with NO gap → there is no stop-window at it. The direct word-scan still
    # extends the END to it.
    words = _words(
        ("вот", 39.0, 39.5),
        ("кто", 39.6, 40.0),  # anchored END lands here, MID-thought
        ("хочет", 40.05, 41.0),
        ("учиться", 41.05, 42.0),
        ("именно", 42.05, 43.0),
        ("поэтому.", 43.05, 44.0),  # terminal punct, but "далее" follows with no gap
        ("далее", 44.05, 60.0),
    )
    out = _extend_to_sentence_completion(40.0, words, ceiling=200.0)
    assert out[0] == pytest.approx(44.0)  # extended to the END of "поэтому."
    assert out[1] == pytest.approx(44.05)  # start of the following word "далее"


def test_extend_to_sentence_completion_already_on_terminus_stays_put():
    # The anchored END is already at the end of a terminus word → distance 0, no move.
    words = _words(("слово.", 0.0, 40.0), ("дальше", 40.1, 60.0))
    assert _extend_to_sentence_completion(40.0, words, ceiling=200.0)[0] == pytest.approx(40.0)


def test_extend_to_sentence_completion_no_terminus_in_budget_keeps_end():
    # The only terminus is BEYOND SENTENCE_COMPLETE_BUDGET_S ahead → fail-safe, keep.
    far = 40.0 + SENTENCE_COMPLETE_BUDGET_S + 2.0
    words = _words(("a", 39.0, 40.0), ("b", 40.05, far - 0.05), ("конец.", far - 0.04, far))
    assert _extend_to_sentence_completion(40.0, words, ceiling=200.0) is None


def test_extend_to_sentence_completion_respects_ceiling():
    # A terminus within the time budget but PAST the ceiling is rejected (cap holds).
    words = _words(("a", 39.0, 40.0), ("конец.", 42.0, 44.0), ("next", 44.1, 60.0))
    assert _extend_to_sentence_completion(40.0, words, ceiling=43.0) is None  # 44.0 > 43.0


def test_extend_to_sentence_completion_uses_restored_sent_end_flag():
    # No terminal punctuation anywhere; a restored sent_end=True flag still drives it.
    words = annotate_sentence_ends(
        _words(
            ("кто", 39.6, 40.0),
            ("хочет", 40.05, 41.0),
            ("научиться", 41.05, 43.0),  # LONG pause (43→44.0) restores sent_end here
            ("итак", 44.0, 60.0),
        )
    )
    out = _extend_to_sentence_completion(40.0, words, ceiling=200.0)
    assert out[0] == pytest.approx(43.0)  # restored terminus end


def test_extend_to_sentence_completion_budget_is_generous_past_max_extend():
    # A terminus 7s ahead — beyond the old MAX_EXTEND_END_S=5 but inside the
    # SENTENCE_COMPLETE_BUDGET_S — is reached. Completing the thought beats tightness.
    assert SENTENCE_COMPLETE_BUDGET_S > MAX_EXTEND_END_S
    words = _words(
        ("кто", 39.6, 40.0), ("длинно", 40.1, 46.9), ("поэтому.", 46.95, 47.0), ("z", 47.05, 60.0)
    )
    out = _extend_to_sentence_completion(40.0, words, ceiling=200.0)
    assert out[0] == pytest.approx(47.0)  # 7s forward — within the generous budget


def test_budget_is_sixteen_seconds():
    # The raised budget (10.0 → 16.0) is what lets a long CTA sentence finish.
    assert SENTENCE_COMPLETE_BUDGET_S == pytest.approx(16.0)


def test_extend_to_sentence_completion_reaches_terminus_14s_out_that_10s_missed():
    # THE founder fix: a long CTA sentence ("…для тех, кто …") whose terminus sits
    # ~14s ahead. The OLD 10s budget could not reach it (clip ended mid-sentence);
    # the new 16s budget does. Still far below MAX_CLIP_S so the cap never trips.
    terminus_end = 40.0 + 14.0  # 14s forward: >10 (old miss) and <16 (new reach)
    words = _words(
        ("для", 39.0, 39.4),
        ("тех", 39.45, 39.7),
        ("кто", 39.75, 40.0),  # anchored END lands here, MID-thought (the CTA dangle)
        ("хочет", 40.1, 45.0),
        ("научиться", 45.05, 50.0),
        ("монтажу.", terminus_end - 0.05, terminus_end),  # the real full-stop terminus
        ("далее", terminus_end + 0.05, 70.0),
    )
    # Sanity: this terminus is unreachable under the OLD 10s budget but reachable now.
    assert 10.0 < (terminus_end - 40.0) <= SENTENCE_COMPLETE_BUDGET_S
    out = _extend_to_sentence_completion(40.0, words, ceiling=200.0)
    assert out[0] == pytest.approx(terminus_end)  # extended to finish the CTA sentence


def test_extend_to_sentence_completion_16s_budget_still_capped_by_ceiling():
    # The raised budget must NEVER produce a clip past the hard cap: a terminus 14s
    # ahead is inside the 16s time budget but PAST the ceiling → declined (cap holds).
    terminus_end = 40.0 + 14.0
    words = _words(
        ("кто", 39.75, 40.0),
        ("длинно", 40.1, 50.0),
        ("конец.", terminus_end - 0.05, terminus_end),
        ("next", terminus_end + 0.05, 70.0),
    )
    # ceiling sits BELOW the terminus → the MAX_CLIP_S/duration cap wins over budget.
    assert _extend_to_sentence_completion(40.0, words, ceiling=terminus_end - 1.0) is None


def test_extend_to_sentence_completion_no_words_keeps_end():
    assert _extend_to_sentence_completion(40.0, (), ceiling=200.0) is None


# ── refine_boundaries — production-path sentence completion (c1/c5) ───────────


def test_refine_end_completes_sentence_when_anchored_mid_thought_no_gap():
    # THE c1/c5 SCENARIO: the (phrase-anchored) END floats onto "кто" mid-sentence.
    # The real terminus "поэтому." sits 4s ahead with NO gap after it, so the old
    # stop-window forward-extension can't see it. refine_boundaries must now complete
    # the thought via the direct word-scan.
    words = _words(
        ("для", 0.0, 20.0),
        ("тех", 20.05, 38.0),
        ("кто", 39.6, 40.0),  # anchored END here, MID-thought (c1 "...для тех, кто")
        ("хочет", 40.05, 41.0),
        ("научиться", 41.05, 42.0),
        ("именно", 42.05, 43.0),
        ("поэтому.", 43.05, 44.0),  # terminus; next word 1s away so the full trail pad fits
        ("далее", 45.0, 60.0),
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=120.0)
    assert end == pytest.approx(44.0 + TRAIL_PAD_S)  # completed the sentence


def test_refine_end_clean_period_clip_stays_put():
    # c3/c4 SCENARIO: the clip already ENDS on a sentence terminus ("снизу.") →
    # the completion extension is a no-op; the clean end is preserved + trail pad.
    words = _words(
        ("посмотрите", 0.0, 38.0),
        ("снизу.", 38.05, 40.0),  # already a clean sentence end
        ("теперь", 42.0, 60.0),  # gap 2.0 → a stop window confirms the end too
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=120.0)
    assert end == pytest.approx(40.0 + TRAIL_PAD_S)  # unchanged, no over-extension


def test_refine_end_completion_pad_never_slivers_next_word():
    # The "…сто. Три" fix: when the next word starts WITHIN the trail pad of the
    # terminus, the END is clamped to that next word's onset so it never bleeds in.
    words = _words(
        ("длинно", 0.0, 38.0),
        ("кто", 39.6, 40.0),  # anchored END mid-thought
        ("сто.", 41.05, 43.0),  # terminus; "три" starts only 0.05s later (< TRAIL_PAD_S)
        ("три", 43.05, 60.0),
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=120.0)
    assert end == pytest.approx(43.05)  # clamped to "три"'s onset, NOT 43.0 + 0.20


def test_refine_end_completion_capped_by_max_clip_duration():
    # A true terminus exists but completing to it would push the clip past MAX_CLIP_S
    # → the completion ceiling rejects it; the in-band end is kept (no overrun).
    far = MAX_CLIP_S + 2.0
    words = _words(
        ("a", 0.0, MAX_CLIP_S - 1.0),
        ("кто", MAX_CLIP_S - 0.9, MAX_CLIP_S - 0.5),  # anchored END mid-thought
        ("поэтому.", far, far + 1.0),  # terminus, but past the hard cap
        ("next", far + 1.05, far + 4.0),
    )
    _, end = refine_boundaries(0.0, MAX_CLIP_S - 0.5, words, (), duration=far + 10.0)
    assert end <= MAX_CLIP_S  # the Shorts hard cap survives the truer-but-farther terminus


def test_refine_end_completion_never_past_video_duration():
    # The terminus end exceeds the clip's video duration → clamp to duration, never beyond.
    words = _words(
        ("кто", 39.6, 40.0),  # anchored END mid-thought
        ("поэтому.", 41.0, 44.0),  # terminus end 44.0 > duration 42.0
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=42.0)
    assert end <= 42.0


def test_refine_end_completion_skipped_when_it_breaks_max_clip_revert():
    # If extending would drive the clip over MAX_CLIP_S, completion is declined and the
    # validated (pre-completion) end is preserved — fail-safe to a still-clean bound.
    words = _words(
        ("a", 0.0, 30.0),
        ("снизу.", 30.05, 40.0),  # a clean terminus the snap already lands the end on
        ("поэтому.", 40.0 + MAX_CLIP_S, 40.0 + MAX_CLIP_S + 1.0),  # terminus past the cap
    )
    _, end = refine_boundaries(0.0, 40.0, words, (), duration=400.0)
    assert end == pytest.approx(40.0 + TRAIL_PAD_S)  # stays on the clean in-band terminus


def test_refine_start_unchanged_by_sentence_completion():
    # REGRESSION: completing the END must not move the START — the hook stays put.
    words = _words(
        ("a", 0.0, 5.0),
        ("b", 12.0, 39.0),  # gap 5→12 → resume@12 (start snap)
        ("кто", 39.6, 40.0),
        ("поэтому.", 41.0, 44.0),  # gap 40→41 + terminus
        ("z", 44.05, 60.0),
    )
    start, _ = refine_boundaries(11.5, 40.0, words, (), duration=120.0)
    assert start == pytest.approx(12.0 - 0.08)  # hook preserved exactly


def test_refine_end_completion_never_shrinks_below_settled_end():
    # The settled END already sits PAST a terminus word (the existing snap landed it
    # on a later breath in trailing silence). Completion must NOT pull the END back to
    # that earlier terminus — it only ever moves FORWARD (candidate_end > new_end gate).
    words = _words(
        ("a", 0.0, 30.0),
        ("готово.", 30.05, 38.0),  # an EARLIER terminus, before the settled end
        ("b", 38.05, 60.0),  # speech continues; no later terminus in budget
    )
    # Target 41.0 with no nearer stop window → END stays at the clamped LLM end (41.0),
    # which is already PAST the "готово." terminus end (38.0). Completion finds no
    # FORWARD terminus and the earlier one is gated out → END unchanged.
    _, end = refine_boundaries(0.0, 41.0, words, (), duration=120.0)
    assert end == pytest.approx(41.0)  # not pulled back to 38.0 — forward-only
    assert MIN_CLIP_S <= end <= 120.0


def test_recall_candidates_completes_mid_thought_end_in_production_chain():
    # END-TO-END through recall_candidates (the production chain stages use): the LLM
    # end (40.3) lands mid-thought on "кто"; the chain forward-completes to "поэтому.".
    transcript = {"duration": 120.0, "segments": [{"start": 0, "end": 120, "text": "x"}]}
    llm = FakeLLM([_hl("A", 0.0, 40.3, 70)])
    word_segments = [
        {
            "words": [
                {"word": "для", "start": 0.0, "end": 20.0},
                {"word": "тех", "start": 20.05, "end": 38.0},
                {"word": "кто", "start": 39.6, "end": 40.0},  # LLM end lands here
                {"word": "хочет", "start": 40.05, "end": 41.0},
                {"word": "поэтому.", "start": 41.05, "end": 43.0},  # terminus; next word 1s away
                {"word": "далее", "start": 44.0, "end": 60.0},
            ]
        }
    ]
    cands = recall_candidates(transcript, _signals(), llm_fn=llm, word_segments=word_segments, k=1)
    assert cands[0].end_time == pytest.approx(43.0 + TRAIL_PAD_S)  # completed the thought
