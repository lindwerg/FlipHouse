"""Unit coverage for engine/escalation.py — pure detector + fail-closed re-score."""

import logging

from fliphouse_worker.engine.escalation import (
    _default_rescore,
    borderline_indices,
    escalate_borderline,
)
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import ClipScore
from fliphouse_worker.llm import Profile
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.tiers import BUDGET, AvScope, TierConfig


def _scored(agg, conf=80, *, model="m", usage=None):
    return ScoredClip(
        agg, {}, conf, ["text"], model, {"prompt_tokens": 1} if usage is None else usage
    )


def _cs(agg, conf=80, *, used_video=True, title="t"):
    cand = CandidateClip(title, 0.0, 30.0, 50.0, 0.0, "txt")
    return ClipScore(candidate=cand, scored=_scored(agg, conf), used_video=used_video)


def _tier(**kw):
    base = dict(
        name="t",
        av_scope=AvScope.ALL,
        escalate=True,
        escalation_profile=Profile.OFFER_MATCH,
        escalation_max_clips=3,
    )
    base.update(kw)
    return TierConfig(**base)


# ── borderline_indices (pure detector) ───────────────────────────────────


def test_borderline_empty_ranked():
    assert borderline_indices([], 3, conf_floor=70, gap_eps=5.0, max_escalations=3) == ()


def test_borderline_max_escalations_zero():
    ranked = [_cs(90), _cs(50, conf=10)]
    assert borderline_indices(ranked, 1, conf_floor=70, gap_eps=5.0, max_escalations=0) == ()


def test_borderline_primary_rank_margin():
    # cutoff at k=2 → boundary = ranked[1].aggregate = 70; clip near it is borderline.
    ranked = [_cs(90), _cs(70), _cs(68), _cs(40)]
    out = borderline_indices(ranked, 2, conf_floor=0, gap_eps=5.0, max_escalations=5)
    assert set(out) == {1, 2}  # 70 (dist 0) and 68 (dist 2) within eps 5; 90/40 far


def test_borderline_secondary_confidence_only():
    # k==len → no cutoff contest → only confidence rule fires.
    ranked = [_cs(90, conf=60), _cs(80, conf=90)]
    out = borderline_indices(ranked, 2, conf_floor=70, gap_eps=5.0, max_escalations=5)
    assert out == (0,)


def test_borderline_k_zero_confidence_only():
    ranked = [_cs(90, conf=10), _cs(80, conf=90)]
    out = borderline_indices(ranked, 0, conf_floor=70, gap_eps=5.0, max_escalations=5)
    assert out == (0,)


def test_borderline_k_greater_than_len_no_indexerror():
    ranked = [_cs(90, conf=60)]
    out = borderline_indices(ranked, 9, conf_floor=70, gap_eps=5.0, max_escalations=5)
    assert out == (0,)


def test_borderline_no_contest_all_confident_not_flagged():
    # k >= len → no cutoff contest; every clip confident → nothing escalates.
    ranked = [_cs(90, conf=90), _cs(50, conf=90)]
    out = borderline_indices(ranked, 5, conf_floor=70, gap_eps=5.0, max_escalations=5)
    assert out == ()


def test_borderline_marginal_survivor_far_clip_excluded():
    # Contest at k=2 (boundary = ranked[1]=85). Far, confident clips (40, 30) excluded;
    # only the marginal survivor (dist 0) is flagged.
    ranked = [_cs(90, conf=90), _cs(85, conf=90), _cs(40, conf=90), _cs(30, conf=90)]
    out = borderline_indices(ranked, 2, conf_floor=70, gap_eps=5.0, max_escalations=5)
    assert out == (1,)


def test_borderline_caps_and_orders_by_distance_then_index():
    # boundary = ranked[1].aggregate = 71. dists: 0→19, 1→0, 2→1, 3→2 (all but 0 within eps 5).
    ranked = [_cs(90), _cs(71), _cs(72), _cs(69)]
    out = borderline_indices(ranked, 2, conf_floor=0, gap_eps=5.0, max_escalations=2)
    assert out == (1, 2)  # nearest two by distance (0 then 1), stable index tie-break


# ── escalate_borderline (fail-closed re-score) ───────────────────────────


def test_escalate_noop_when_tier_not_escalating():
    ranked = [_cs(90), _cs(50, conf=10)]
    out, count, usages = escalate_borderline(
        ranked, object(), "v.mp4", k=1, tier=BUDGET, cut_fn=None
    )
    assert out is ranked and count == 0 and usages == ()


def test_escalate_noop_when_max_clips_zero():
    ranked = [_cs(50, conf=10)]
    out, count, usages = escalate_borderline(
        ranked, object(), "v.mp4", k=1, tier=_tier(escalation_max_clips=0), cut_fn=None
    )
    assert out is ranked and count == 0 and usages == ()


def test_escalate_noop_when_no_borderline():
    ranked = [_cs(90, conf=90), _cs(80, conf=90)]
    out, count, usages = escalate_borderline(
        ranked, object(), "v.mp4", k=5, tier=_tier(escalation_confidence_floor=70), cut_fn=None
    )
    assert out is ranked and count == 0 and usages == ()


def test_escalate_upgrades_and_reports_profile_and_usage():
    seen = {}

    def fake_rescore(clip, scorer, src, *, profile, cut_fn):
        seen["profile"] = profile
        return _scored(99.0, model="strong", usage={"prompt_tokens": 7})

    ranked = [_cs(50, conf=10, title="x")]
    out, count, usages = escalate_borderline(
        ranked,
        object(),
        "v.mp4",
        k=5,
        tier=_tier(),
        cut_fn=None,
        _select_fn=lambda *a, **k: (0,),
        _rescore_fn=fake_rescore,
    )
    assert seen["profile"] is Profile.OFFER_MATCH
    assert count == 1
    assert out[0].scored.aggregate == 99.0
    assert usages == (("strong", {"prompt_tokens": 7}),)
    assert ranked[0].scored.aggregate == 50.0  # original list not mutated


def test_escalate_fail_closed_keeps_original_uncounted(caplog):
    def boom(clip, scorer, src, *, profile, cut_fn):
        raise RuntimeError("escalation provider down")

    ranked = [_cs(50, conf=10)]
    with caplog.at_level(logging.WARNING):
        out, count, usages = escalate_borderline(
            ranked,
            object(),
            "v.mp4",
            k=5,
            tier=_tier(),
            cut_fn=None,
            _select_fn=lambda *a, **k: (0,),
            _rescore_fn=boom,
        )
    assert count == 0 and usages == ()
    assert out[0].scored.aggregate == 50.0  # original kept, not dropped
    assert any("keeping original" in r.message for r in caplog.records)


class _RecordingScorer:
    def __init__(self):
        self.calls = []

    def score_clip(
        self, text, duration_s=None, *, video=None, video_mime=None, profile_override=None
    ):
        self.calls.append({"video": video, "profile_override": profile_override})
        return _scored(88.0)


def test_default_rescore_av_clip_recuts_and_passes_profile():
    cuts = []
    scorer = _RecordingScorer()
    clip = _cs(50, used_video=True)
    _default_rescore(
        clip,
        scorer,
        "v.mp4",
        profile=Profile.OFFER_MATCH,
        cut_fn=lambda s, a, b: cuts.append((a, b)) or b"WEBM",
    )
    assert cuts == [(0.0, 30.0)]  # re-cut
    assert scorer.calls[0]["video"] == b"WEBM"
    assert scorer.calls[0]["profile_override"] is Profile.OFFER_MATCH


def test_default_rescore_text_clip_also_gets_av():
    # Escalation promotes a text-only clip to FULL A/V: it cuts and attaches video
    # even though the clip was first scored text-only (the contested ranking may be
    # wrong precisely because A/V was never seen).
    cuts = []
    scorer = _RecordingScorer()
    clip = _cs(50, used_video=False)
    _default_rescore(
        clip,
        scorer,
        "v.mp4",
        profile=Profile.OFFER_MATCH,
        cut_fn=lambda s, a, b: cuts.append((a, b)) or b"WEBM",
    )
    assert cuts == [(0.0, 30.0)]  # cut even though the clip was text-only
    assert scorer.calls[0]["video"] == b"WEBM"
    assert scorer.calls[0]["profile_override"] is Profile.OFFER_MATCH
