"""Unit coverage for engine/cascade.py — all stages injected; cutter faked, map serial.

Every ``select_clips`` call stubs ``_cut_fn`` (no ffmpeg) and injects a serial
``_score_fn`` (no threads), so the cascade logic is exercised deterministically.
"""

from fliphouse_worker.clipping import SAFE_FINALIST_PRESET
from fliphouse_worker.engine.cascade import (
    MIN_FLOOR_CLIPS,
    CascadeResult,
    SelectedClip,
    _selection_floor,
    select_clips,
)
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import ClipScore, finalist_cut, score_candidates
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.tiers import BUDGET, IDEAL


def _fake_cut(src, start, end):
    return b"WEBM"


def _serial_map(fn, items):
    return [fn(i) for i in items]


def _serial_score(cands, scorer, src, *, cut_fn, tier=IDEAL, **_):
    return score_candidates(cands, scorer, src, cut_fn=cut_fn, _map_fn=_serial_map, tier=tier)


def _select(
    cands,
    scorer,
    *,
    threshold=0.0,
    cap=40,
    cut_fn=_fake_cut,
    signals_fn=lambda s: None,
    tier=IDEAL,
    transcript=None,
):
    """Returns the ranked clips tuple (.clips); use ``_select_result`` for the full record."""
    return _select_result(
        cands,
        scorer,
        threshold=threshold,
        cap=cap,
        cut_fn=cut_fn,
        signals_fn=signals_fn,
        tier=tier,
        transcript=transcript,
    ).clips


def _select_result(
    cands,
    scorer,
    *,
    threshold=0.0,
    cap=40,
    cut_fn=_fake_cut,
    signals_fn=lambda s: None,
    tier=IDEAL,
    transcript=None,
):
    return select_clips(
        {} if transcript is None else transcript,
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=scorer,
        quality_threshold=threshold,
        safety_cap=cap,
        tier=tier,
        _signals_fn=signals_fn,
        _cut_fn=cut_fn,
        _score_fn=_serial_score,
    )


def _cand(title, start, end, text=None):
    return CandidateClip(
        title=title,
        start_time=start,
        end_time=end,
        llm_score=50.0,
        dsp_prior=0.0,
        text_excerpt=text or title,
    )


def _scored(aggregate):
    return ScoredClip(
        aggregate=aggregate,
        sub_scores={},
        confidence=80,
        modalities_used=["text"],
        model_used="fake",
        raw_usage={},
    )


class FakeScorer:
    """score_clip(text, duration_s, **kw) → ScoredClip whose aggregate comes from a text→score map."""

    def __init__(self, scores):
        self._scores = scores
        self.calls = []

    def score_clip(self, text, duration_s=None, **kw):
        self.calls.append((text, duration_s))
        return _scored(self._scores[text])


class _AvScorer:
    """Reports real A/V modalities when a clip is attached → reason AV_OK."""

    def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
        modalities = ["text", "visual", "audio"] if video is not None else ["text"]
        return ScoredClip(
            aggregate=70.0,
            sub_scores={},
            confidence=80,
            modalities_used=modalities,
            model_used="fake",
            raw_usage={},
        )


def _recall(candidates):
    def _fn(transcript, signals):
        _fn.seen = (transcript, signals)
        return tuple(candidates)

    return _fn


def test_select_clips_ranks_by_aggregate_descending():
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0})
    out = _select(cands, scorer)  # threshold 0 → all kept, sorted desc
    assert [c.candidate.title for c in out] == ["b", "c", "a"]
    assert [c.rank for c in out] == [0, 1, 2]
    assert all(isinstance(c, SelectedClip) for c in out)


def test_select_clips_threshold_gate_drops_sub_threshold():
    # Four above-bar clips (>= floor of 3) so the threshold — not the floor — gates;
    # the single sub-bar clip "a" (40) is dropped.
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c", "d", "e"))]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0, "d": 80.0, "e": 60.0})
    out = _select(cands, scorer, threshold=55.0)  # a (40) below the bar
    assert [c.candidate.title for c in out] == ["b", "d", "c", "e"]


def test_select_clips_threshold_is_the_gate_not_a_count():
    # SAME candidates, DIFFERENT thresholds → DIFFERENT counts (gate, not k). Five
    # clips with four above 55 keep the count above the floor (3) so the THRESHOLD
    # governs; the lowest threshold passes all five.
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c", "d", "e"))]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0, "d": 80.0, "e": 60.0})
    assert len(_select(cands, scorer, threshold=35.0)) == 5
    assert len(_select(cands, scorer, threshold=65.0)) == 3  # b, d, c
    assert len(_select(cands, scorer, threshold=85.0)) == 3  # only b clears, floor rescues to 3


def test_select_clips_safety_cap_bounds_supra_threshold_count():
    cands = [_cand(f"c{i}", i * 100, i * 100 + 20) for i in range(50)]
    scorer = FakeScorer({f"c{i}": 80.0 for i in range(50)})  # all clear the bar
    out = _select(cands, scorer, threshold=55.0, cap=40)
    assert len(out) == 40  # capped, not 50


def test_select_clips_scores_each_candidate_with_duration():
    cands = [_cand("a", 0, 20), _cand("b", 30, 55)]
    scorer = FakeScorer({"a": 10.0, "b": 20.0})
    _select(cands, scorer)
    assert ("a", 20.0) in scorer.calls and ("b", 25.0) in scorer.calls


def test_select_clips_final_dedupe_drops_overlapping_lower():
    cands = [_cand("a", 0, 20), _cand("b", 2, 22)]  # ~90% overlap
    scorer = FakeScorer({"a": 90.0, "b": 40.0})  # a wins, b dropped
    out = _select(cands, scorer)
    assert [c.candidate.title for c in out] == ["a"]


def test_select_clips_final_dedupe_drops_long_containing_short():
    cands = [_cand("short", 0, 20), _cand("long", 0, 180)]  # long fully contains short
    scorer = FakeScorer({"short": 90.0, "long": 40.0})  # short kept first → long dropped
    out = _select(cands, scorer)
    assert [c.candidate.title for c in out] == ["short"]


def test_select_clips_empty_candidates():
    out = _select([], FakeScorer({}))
    assert out == ()


def test_select_clips_single_candidate_over_threshold_kept():
    out = _select([_cand("a", 0, 20)], FakeScorer({"a": 50.0}))
    assert len(out) == 1


def test_select_clips_passes_src_to_signals_fn():
    seen = {}

    def fake_signals(src):
        seen["src"] = src
        return "SIGNALS"

    recall = _recall([_cand("a", 0, 20)])
    select_clips(
        {},
        "clip.mp4",
        recall_fn=recall,
        scorer=FakeScorer({"a": 50.0}),
        quality_threshold=0.0,
        _signals_fn=fake_signals,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
    )
    assert seen["src"] == "clip.mp4"
    assert recall.seen[1] == "SIGNALS"  # signals forwarded to recall_fn


def test_select_clips_av_kwargs_forwarded():
    cut_calls = []

    def recording_cut(src, start, end):
        cut_calls.append((src, start, end))
        return b"WEBMBYTES"

    class RecordingScorer:
        def __init__(self):
            self.kw = []

        def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
            self.kw.append((video, video_mime))
            return _scored(70.0)

    scorer = RecordingScorer()
    out = _select([_cand("a", 5, 25)], scorer, cut_fn=recording_cut)
    assert cut_calls == [("v.mp4", 5, 25)]
    assert scorer.kw == [(b"WEBMBYTES", "video/webm")]
    assert out[0].used_video is True


def test_select_clips_text_fallback_in_cascade():
    def failing_cut(src, start, end):
        raise OSError("ffmpeg missing")

    out = _select([_cand("a", 0, 20)], FakeScorer({"a": 60.0}), cut_fn=failing_cut)
    assert len(out) == 1
    assert out[0].used_video is False  # fell back to text but still ranked
    assert out[0].scored.aggregate == 60.0


# ── tier / escalation / cost-record (P2-S7) ──────────────────────────────


def test_select_clips_returns_cascade_result():
    res = _select_result([_cand("a", 0, 20)], FakeScorer({"a": 50.0}))
    assert isinstance(res, CascadeResult)
    assert isinstance(res.clips, tuple)
    assert res.cost_record.av_clip_count + res.cost_record.text_clip_count == 1


def test_empty_candidates_still_returns_cost_record():
    res = _select_result([], FakeScorer({}))
    assert res.clips == ()
    assert res.cost_record.total_usd == 0.0


# ── scene-cut threading (REFRAME Phase 0): cuts ride the CascadeResult ────────


class _FakeCut:
    def __init__(self, time_s: float) -> None:
        self.time_s = time_s


class _FakeSignals:
    def __init__(self, *times: float) -> None:
        self.scene_cuts = tuple(_FakeCut(t) for t in times)


def test_select_clips_carries_scene_cut_times_from_signals():
    res = _select_result(
        [_cand("a", 0, 20)],
        FakeScorer({"a": 50.0}),
        signals_fn=lambda s: _FakeSignals(12.0, 48.5),
    )
    assert res.scene_cut_times == (12.0, 48.5)


def test_select_clips_carries_scene_cut_times_on_empty_candidates():
    res = _select_result([], FakeScorer({}), signals_fn=lambda s: _FakeSignals(7.0))
    assert res.clips == ()
    assert res.scene_cut_times == (7.0,)


def test_select_clips_scene_cut_times_default_empty_when_signals_lack_cuts():
    # A stub/None signals object (no .scene_cuts) degrades to no-snap, never crashes.
    res = _select_result([_cand("a", 0, 20)], FakeScorer({"a": 50.0}), signals_fn=lambda s: None)
    assert res.scene_cut_times == ()


def test_budget_tier_end_to_end_text_only():
    res = _select_result(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        FakeScorer({"a": 50.0, "b": 60.0}),
        tier=BUDGET,
    )
    assert all(c.used_video is False for c in res.clips)
    assert res.cost_record.text_clip_count == 2
    assert res.cost_record.av_clip_count == 0
    assert res.cost_record.escalation_count == 0


def test_budget_tier_degradation_counts_all_budget_skipped():
    res = _select_result(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        FakeScorer({"a": 50.0, "b": 60.0}),
        tier=BUDGET,
    )
    # BUDGET never cuts video → every clip is an intentional text skip, not a failure.
    assert res.degradation.budget_skipped == 2
    assert res.degradation.av_succeeded == 0
    assert res.degradation.av_failed_fellback == 0
    assert res.degradation.modalities_dropped == 0


def test_degradation_av_success_counted_from_pre_escalation_snapshot():
    # IDEAL cuts every clip; FakeScorer reports visual/audio when video present → AV_OK.
    res = _select_result([_cand("a", 0, 20), _cand("b", 30, 50)], _AvScorer())
    assert res.degradation.av_succeeded == 2
    assert res.degradation.budget_skipped == 0


def test_empty_candidates_degradation_is_zero():
    res = _select_result([], FakeScorer({}))
    assert res.degradation.av_succeeded == 0
    assert res.degradation.budget_skipped == 0


def test_escalation_receives_threshold_cutoff_as_k():
    # The cutoff index (clips >= threshold) is fed to escalation as its k= margin
    # reference, so escalation can flag clips straddling the bar. Here threshold=55
    # → cutoff=2 (b=90, c=70 over; a=40 under).
    seen = {}

    def spy(ranked, scorer, src, *, k, tier, cut_fn):
        seen["k"] = k
        return ranked, 0, ()

    cands = [_cand("a", 0, 20), _cand("b", 40, 60), _cand("c", 80, 100)]
    select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0}),
        quality_threshold=55.0,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
        _escalate_fn=spy,
    )
    assert seen["k"] == 2  # cutoff index, not a hardcoded k


def test_escalation_injection_lifts_clip_over_threshold_and_flows_to_cost_record():
    def boost_a(ranked, scorer, src, *, k, tier, cut_fn):
        out = []
        usages = []
        for cs in ranked:
            if cs.candidate.title == "a":
                lifted = ScoredClip(100.0, {}, 80, ["text"], "strong", {"prompt_tokens": 1})
                out.append(
                    ClipScore(candidate=cs.candidate, scored=lifted, used_video=cs.used_video)
                )
                usages.append(("strong", {"prompt_tokens": 1}))
            else:
                out.append(cs)
        return out, 1, tuple(usages)

    cands = [_cand("a", 0, 20), _cand("b", 40, 60), _cand("c", 80, 100)]
    res = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0}),
        quality_threshold=55.0,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
        _escalate_fn=boost_a,
    )
    # Below the bar 'a' (40) is dropped; the boost lifts it to 100 → a,b,c all pass.
    assert [c.candidate.title for c in res.clips] == ["a", "b", "c"]
    assert res.cost_record.escalation_count == 1
    # the escalation call's usage is folded into the cost record.
    assert "strong" in res.cost_record.by_model


def test_production_default_drives_safe_finalist_preset_into_both_cut_sites():
    # ASK #7(b) regression guard: the REAL caller chain (_default_score_clips →
    # select_clips) never passes _cut_fn, so select_clips' own default IS the
    # production cut. It must be ``finalist_cut`` (the SAFE preset) — not the loose
    # ``cut_clip`` default — and that single cut_fn must reach BOTH finalist cut
    # sites: the Stage B fan-out (_score_fn) AND the borderline escalation (_escalate_fn).
    seen = {}

    def score_spy(cands, scorer, src, *, cut_fn, tier=IDEAL, **_):
        seen["score_cut_fn"] = cut_fn
        return score_candidates(cands, scorer, src, cut_fn=cut_fn, _map_fn=_serial_map, tier=tier)

    def escalate_spy(ranked, scorer, src, *, k, tier, cut_fn):
        seen["escalate_cut_fn"] = cut_fn
        return ranked, 0, ()

    select_clips(
        {},
        "v.mp4",
        recall_fn=_recall([_cand("a", 0, 20)]),
        scorer=FakeScorer({"a": 60.0}),
        quality_threshold=55.0,
        _signals_fn=lambda s: None,
        # _cut_fn intentionally NOT injected — exercise the production default.
        _score_fn=score_spy,
        _escalate_fn=escalate_spy,
    )

    # Both cut sites receive the exact SAFE-preset finalist cut, not the loose default.
    assert seen["score_cut_fn"] is finalist_cut
    assert seen["escalate_cut_fn"] is finalist_cut
    assert finalist_cut.keywords["preset"] is SAFE_FINALIST_PRESET


# ── selection floor (FIX 2): threshold-primary, floor as safety net ──────────


def _transcript(duration_s):
    """A transcript whose max segment end == duration_s (drives _selection_floor)."""
    return {"segments": [{"start": 0.0, "end": duration_s}]}


def test_selection_floor_scales_with_duration():
    assert _selection_floor(_transcript(7200.0), safety_cap=40) == 20  # ~2h → 20
    assert _selection_floor(_transcript(1800.0), safety_cap=40) == 5  # 30min → 5


def test_selection_floor_never_below_minimum():
    assert _selection_floor(_transcript(360.0), safety_cap=40) == MIN_FLOOR_CLIPS  # 6min → 3
    assert _selection_floor({}, safety_cap=40) == MIN_FLOOR_CLIPS  # empty → 0s → 3


def test_selection_floor_capped_by_safety_cap():
    assert _selection_floor(_transcript(7200.0), safety_cap=10) == 10  # 20 clamped to cap


def test_floor_rescues_long_video_when_all_below_threshold():
    # Every clip scores under the bar; the floor (top-`floor` by aggregate) rescues
    # them in SCORE order, not chronological. A ~36min source → floor 6 > the 4
    # candidates, so all four are kept — and re-ranked by score, never [a,b,c,d].
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c", "d"))]
    scorer = FakeScorer({"a": 10.0, "b": 40.0, "c": 20.0, "d": 30.0})
    out = _select(cands, scorer, threshold=55.0, transcript=_transcript(2160.0))
    assert [c.candidate.title for c in out] == ["b", "d", "c", "a"]  # score order, not [a,b,c,d]


def test_floor_does_not_truncate_clips_that_clear_threshold():
    # Enough clips clear the bar (>= floor); the floor is inert and the threshold
    # governs — all four supra-threshold clips survive, none truncated to the floor.
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c", "d"))]
    scorer = FakeScorer({"a": 90.0, "b": 80.0, "c": 70.0, "d": 60.0})
    out = _select(cands, scorer, threshold=55.0, transcript=_transcript(360.0))
    assert [c.candidate.title for c in out] == ["a", "b", "c", "d"]  # all kept, not capped to 3


# ── viral-banger bonus re-ranking ────────────────────────────────────────────


def _banger_text():
    # Stacks hook (number + negation) + a quotable line → near-max viral bonus.
    return "Никто не признается: я потерял 100 миллионов. Это всё ложь."


def test_viral_bonus_lifts_a_banger_above_a_flat_clip():
    # The flat clip out-scores the banger on the raw LLM aggregate by a hair; the
    # deterministic banger bonus (hook + quotable) overtakes it so the TOP slot is
    # the разнос clip, not the higher-LLM-but-flat one.
    flat = (
        "Так, давайте сверим расписание встреч на следующую неделю и обсудим "
        "все детали проекта подробно вместе со всей нашей командой"
    )
    cands = [_cand("flat", 0, 20, text=flat), _cand("banger", 30, 50, text=_banger_text())]
    scorer = FakeScorer({flat: 60.0, _banger_text(): 58.0})
    out = _select(cands, scorer)
    assert [c.candidate.title for c in out] == ["banger", "flat"]
    # The flat clip earns no bonus; the banger's boosted aggregate clears it.
    boosted = {c.candidate.title: c.scored.aggregate for c in out}
    assert boosted["flat"] == 60.0  # dead opener → zero bonus, unchanged
    assert boosted["banger"] > 58.0  # lifted by the deterministic prior


def test_viral_bonus_is_capped_at_one_hundred():
    # A maxed-out banger already at aggregate 99 cannot exceed the 0-100 ceiling.
    cands = [_cand("banger", 0, 100, text=_banger_text())]
    scorer = FakeScorer({_banger_text(): 99.0})
    out = _select(cands, scorer)
    assert out[0].scored.aggregate == 100.0  # clamped, not 99 + 8


def test_viral_bonus_inert_for_flat_titles():
    # Single-letter excerpts carry no hook/quotable signal → aggregates unchanged,
    # so the bonus never perturbs an already-correct ordering.
    cands = [_cand("a", 0, 20), _cand("b", 30, 50)]
    scorer = FakeScorer({"a": 90.0, "b": 40.0})
    out = _select(cands, scorer)
    assert [c.candidate.title for c in out] == ["a", "b"]
    assert {c.candidate.title: c.scored.aggregate for c in out} == {"a": 90.0, "b": 40.0}


# ── final comparative rerank seam ────────────────────────────────────────────


def test_rerank_fn_reorders_final_survivors():
    # The injected reranker reverses the survivor order; the cascade applies it and
    # re-numbers ranks 0..n in the NEW order (membership unchanged).
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 90.0, "b": 80.0, "c": 70.0})

    def reverse(survivors):
        return list(reversed(survivors))

    res = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=scorer,
        quality_threshold=0.0,
        tier=IDEAL,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
        _rerank_fn=reverse,
    )
    assert [c.candidate.title for c in res.clips] == ["c", "b", "a"]
    assert [c.rank for c in res.clips] == [0, 1, 2]


def test_default_rerank_is_identity():
    # With no injected reranker the default identity keeps the aggregate order.
    cands = [_cand("a", 0, 20), _cand("b", 30, 50)]
    out = _select(cands, FakeScorer({"a": 40.0, "b": 90.0}))
    assert [c.candidate.title for c in out] == ["b", "a"]
