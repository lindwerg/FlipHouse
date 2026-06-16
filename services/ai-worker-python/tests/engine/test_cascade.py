"""Unit coverage for engine/cascade.py — all stages injected; cutter faked, map serial.

Every ``select_clips`` call stubs ``_cut_fn`` (no ffmpeg) and injects a serial
``_score_fn`` (no threads), so the cascade logic is exercised deterministically.
"""

from fliphouse_worker.engine.cascade import SelectedClip, select_clips
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import score_candidates
from fliphouse_worker.scoring import ScoredClip


def _fake_cut(src, start, end):
    return b"WEBM"


def _serial_map(fn, items):
    return [fn(i) for i in items]


def _serial_score(cands, scorer, src, *, cut_fn):
    return score_candidates(cands, scorer, src, cut_fn=cut_fn, _map_fn=_serial_map)


def _select(cands, scorer, *, k=3, cut_fn=_fake_cut, signals_fn=lambda s: None):
    return select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=scorer,
        k=k,
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


def test_select_clips_returns_top_k_by_aggregate():
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    scorer = FakeScorer({"a": 40.0, "b": 90.0, "c": 70.0})
    out = _select(cands, scorer, k=2)
    assert [c.candidate.title for c in out] == ["b", "c"]
    assert [c.rank for c in out] == [0, 1]
    assert all(isinstance(c, SelectedClip) for c in out)


def test_select_clips_scores_each_candidate_with_duration():
    cands = [_cand("a", 0, 20), _cand("b", 30, 55)]
    scorer = FakeScorer({"a": 10.0, "b": 20.0})
    _select(cands, scorer, k=5)
    assert ("a", 20.0) in scorer.calls and ("b", 25.0) in scorer.calls


def test_select_clips_final_dedupe_drops_overlapping_lower():
    cands = [_cand("a", 0, 20), _cand("b", 2, 22)]  # ~90% overlap
    scorer = FakeScorer({"a": 90.0, "b": 40.0})  # a wins, b dropped
    out = _select(cands, scorer, k=5)
    assert [c.candidate.title for c in out] == ["a"]


def test_select_clips_final_dedupe_drops_long_containing_short():
    cands = [_cand("short", 0, 20), _cand("long", 0, 180)]  # long fully contains short
    scorer = FakeScorer({"short": 90.0, "long": 40.0})  # short kept first → long dropped
    out = _select(cands, scorer, k=5)
    assert [c.candidate.title for c in out] == ["short"]


def test_select_clips_empty_candidates():
    out = _select([], FakeScorer({}), k=3)
    assert out == ()


def test_select_clips_k_larger_than_candidates():
    out = _select([_cand("a", 0, 20)], FakeScorer({"a": 50.0}), k=10)
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
