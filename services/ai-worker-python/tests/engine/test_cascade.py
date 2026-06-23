"""Unit coverage for engine/cascade.py — all stages injected; cutter faked, map serial.

Every ``select_clips`` call stubs ``_cut_fn`` (no ffmpeg) and injects a serial
``_score_fn`` (no threads), so the cascade logic is exercised deterministically.
"""

from fliphouse_worker.engine.cascade import CascadeResult, SelectedClip, select_clips
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import ClipScore, score_candidates
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
):
    """Returns the ranked clips tuple (.clips); use ``_select_result`` for the full record."""
    return _select_result(
        cands, scorer, threshold=threshold, cap=cap, cut_fn=cut_fn, signals_fn=signals_fn, tier=tier
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
):
    return select_clips(
        {},
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
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0})
    out = _select(cands, scorer, threshold=55.0)  # a (40) below the bar
    assert [c.candidate.title for c in out] == ["b", "c"]


def test_select_clips_threshold_is_the_gate_not_a_count():
    # SAME candidates, DIFFERENT thresholds → DIFFERENT counts (gate, not k).
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0})
    assert len(_select(cands, scorer, threshold=35.0)) == 3
    assert len(_select(cands, scorer, threshold=65.0)) == 2
    assert len(_select(cands, scorer, threshold=95.0)) == 0


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
