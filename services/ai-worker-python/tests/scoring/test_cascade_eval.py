"""P2-S5 eval gate: the cascade plumbing must not regress the virality ranking.

Threads each seed clip's text through the full cascade (Stage A recall → Stage B
scorer → aggregate) via a deterministic single-candidate recall and a mock
ClipScorer, then runs the eval-harness. Proves the Stage A→B wiring preserves
ranking with a faithful scorer and is correctly rejected with an inverted one.

NOTE: the harness validates TEXT-RANKING only — ``run_eval`` calls
``scorer_fn(text)`` with no duration, so length_factor / boundary-snapping
effects are out of band of this gate by design (they are not text-rankable).
"""

from __future__ import annotations

from fliphouse_worker.engine.cascade import select_clips
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import score_candidates
from fliphouse_worker.eval import SEED_CLIPS
from fliphouse_worker.scoring import ScoredClip, run_eval

_HUMAN = {c.text: c.human_score for c in SEED_CLIPS}


def _fake_cut(src, start, end):
    return b"WEBM"


def _serial_score(cands, scorer, src, *, cut_fn, tier=None, **_):
    kw = {} if tier is None else {"tier": tier}
    return score_candidates(
        cands, scorer, src, cut_fn=cut_fn, _map_fn=lambda fn, items: [fn(i) for i in items], **kw
    )


class _MockScorer:
    def __init__(self, score_of):
        self._score_of = score_of

    def score_clip(self, text, duration_s=None, **kw):
        return ScoredClip(
            aggregate=float(self._score_of(text)),
            sub_scores={},
            confidence=80,
            modalities_used=["text"],
            model_used="mock",
            raw_usage={},
        )


def _cascade_scorer_fn(score_of):
    def scorer_fn(text: str) -> float:
        def recall_fn(transcript, signals):
            return (CandidateClip("c", 0.0, 30.0, 50.0, 0.0, text),)

        out = select_clips(
            {},
            "x.mp4",
            recall_fn=recall_fn,
            scorer=_MockScorer(score_of),
            k=1,
            _signals_fn=lambda s: None,
            _cut_fn=_fake_cut,
            _score_fn=_serial_score,
        )
        return out.clips[0].scored.aggregate

    return scorer_fn


def test_cascade_passes_eval_with_faithful_scorer():
    report = run_eval(_cascade_scorer_fn(lambda t: _HUMAN[t]))
    assert report.passed is True
    assert report.spearman == 1.0


def test_cascade_fails_eval_with_inverted_scorer():
    report = run_eval(_cascade_scorer_fn(lambda t: 100 - _HUMAN[t]))
    assert report.passed is False
