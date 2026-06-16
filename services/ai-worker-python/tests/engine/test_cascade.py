"""Unit coverage for engine/cascade.py — all three stages injected as fakes."""

from fliphouse_worker.engine.cascade import SelectedClip, select_clips
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.scoring import ScoredClip


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
    """score_clip(text, duration_s) → ScoredClip whose aggregate comes from a text→score map."""

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


def test_select_clips_returns_top_k_by_aggregate():
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0})
    out = select_clips(
        {}, "v.mp4", recall_fn=_recall(cands), scorer=scorer, k=2, _signals_fn=lambda s: None
    )
    assert [c.candidate.title for c in out] == ["b", "c"]
    assert [c.rank for c in out] == [0, 1]
    assert all(isinstance(c, SelectedClip) for c in out)


def test_select_clips_scores_each_candidate_with_duration():
    cands = [_cand("a", 0, 20), _cand("b", 30, 55)]
    scorer = FakeScorer({"a": 10.0, "b": 20.0})
    select_clips(
        {}, "v.mp4", recall_fn=_recall(cands), scorer=scorer, k=5, _signals_fn=lambda s: None
    )
    assert ("a", 20.0) in scorer.calls and ("b", 25.0) in scorer.calls


def test_select_clips_final_dedupe_drops_overlapping_lower():
    cands = [_cand("a", 0, 20), _cand("b", 2, 22)]  # ~90% overlap
    scorer = FakeScorer({"a": 90.0, "b": 40.0})  # a wins, b dropped
    out = select_clips(
        {}, "v.mp4", recall_fn=_recall(cands), scorer=scorer, k=5, _signals_fn=lambda s: None
    )
    assert [c.candidate.title for c in out] == ["a"]


def test_select_clips_final_dedupe_drops_long_containing_short():
    cands = [_cand("short", 0, 20), _cand("long", 0, 180)]  # long fully contains short
    scorer = FakeScorer({"short": 90.0, "long": 40.0})  # short kept first → long dropped
    out = select_clips(
        {}, "v.mp4", recall_fn=_recall(cands), scorer=scorer, k=5, _signals_fn=lambda s: None
    )
    assert [c.candidate.title for c in out] == ["short"]


def test_select_clips_empty_candidates():
    out = select_clips(
        {}, "v.mp4", recall_fn=_recall([]), scorer=FakeScorer({}), k=3, _signals_fn=lambda s: None
    )
    assert out == ()


def test_select_clips_k_larger_than_candidates():
    cands = [_cand("a", 0, 20)]
    out = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=FakeScorer({"a": 50.0}),
        k=10,
        _signals_fn=lambda s: None,
    )
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
        k=1,
        _signals_fn=fake_signals,
    )
    assert seen["src"] == "clip.mp4"
    assert recall.seen[1] == "SIGNALS"  # signals forwarded to recall_fn
