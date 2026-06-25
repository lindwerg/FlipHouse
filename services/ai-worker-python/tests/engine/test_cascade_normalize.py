"""RANK-1 coverage: per-model score normalization before pooling/sorting.

Absolute LLM-judge scores are not comparable across models — a generous lite model
must not bury a stricter flash A/V finalist. These tests pin both the pure
``normalized_rank_values`` and its integration in ``select_clips``: a flash-A/V 65
outranks a lite-text 70 after normalization, and normalization is a no-op (ranking
unchanged) when every clip shares one model.
"""

from __future__ import annotations

from dataclasses import dataclass

from fliphouse_worker.engine.cascade import select_clips
from fliphouse_worker.engine.normalize import (
    MIN_GROUP_FOR_Z,
    normalized_rank_values,
)
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import score_candidates
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.tiers import BUDGET


# ── pure normalize unit ─────────────────────────────────────────────────────
@dataclass(frozen=True)
class _Scored:
    aggregate: float
    model_used: str


@dataclass(frozen=True)
class _Clip:
    scored: _Scored


def _clip(aggregate: float, model: str) -> _Clip:
    return _Clip(_Scored(aggregate, model))


def test_normalization_is_noop_ordering_for_a_single_model():
    # One model, a big group → within-group z-score is a monotonic transform of the
    # raw aggregate, so the ranking is byte-for-byte the raw ranking.
    clips = [_clip(a, "lite") for a in (90.0, 40.0, 70.0, 55.0)]
    rv = normalized_rank_values(clips)
    raw_order = sorted(range(len(clips)), key=lambda i: clips[i].scored.aggregate, reverse=True)
    norm_order = sorted(range(len(clips)), key=lambda i: rv[i], reverse=True)
    assert norm_order == raw_order


def test_single_clip_single_model_normalizes_without_crashing():
    # Degenerate: one clip, one model → tiny-group path, reference is itself.
    rv = normalized_rank_values([_clip(80.0, "lite")])
    assert len(rv) == 1
    assert isinstance(rv[0], float)


def test_stricter_model_av_clip_outranks_generous_model_text_clip():
    # The lite (text) model is GENEROUS (baseline ~85); the flash A/V model is
    # STRICTER (baseline ~55). With the calibrated baselines, the flash 65 sits HIGH
    # for flash and must out-rank the generous lite 70 (which sits below lite's own
    # mean). This is the RANK-1 flagship: the A/V finalist is not buried by lite.
    lite_group = [_clip(a, "lite") for a in (88.0, 90.0, 85.0, 70.0)]  # 70 is the loser
    flash = _clip(65.0, "flash")  # the A/V finalist — stricter model, fewer points
    clips = [*lite_group, flash]
    # baselines encode strictness: flash's typical score (55) is far below lite's (85).
    rv = normalized_rank_values(clips, offsets={"flash": 55.0})
    flash_rv = rv[-1]
    lite70_rv = rv[3]
    assert flash_rv > lite70_rv  # the stricter A/V 65 beats the generous text 70


def test_tiny_group_baseline_offset_lifts_a_stricter_model():
    # A LOWER baseline for the stricter model lifts its clip UP the axis.
    clips = [
        _clip(70.0, "strict"),
        _clip(70.0, "ref-a"),
        _clip(70.0, "ref-b"),
        _clip(70.0, "ref-c"),
    ]
    # make ref the big group so its mean is the default; strict gets a low baseline.
    clips = [_clip(70.0, "strict"), *[_clip(80.0, "ref") for _ in range(3)]]
    base = normalized_rank_values(clips, offsets={})
    lifted = normalized_rank_values(clips, offsets={"strict": 50.0})
    assert lifted[0] > base[0]  # strict model promoted by its lower baseline
    assert lifted[1:] == base[1:]  # the big ref group is untouched (self-z-scored)


def test_z_score_threshold_is_three():
    assert MIN_GROUP_FOR_Z == 3


# ── integration: cascade sorts on the normalized value ──────────────────────
def _fake_cut(src, start, end):
    return b"WEBM"


def _serial_score(cands, scorer, src, *, cut_fn, tier=BUDGET, **_):
    return score_candidates(
        cands,
        scorer,
        src,
        cut_fn=cut_fn,
        _map_fn=lambda fn, items: [fn(i) for i in items],
        tier=tier,
    )


def _cand(title, start, end):
    return CandidateClip(title, start, end, 50.0, 0.0, title)


class _ModelScorer:
    """Stamps a per-text model + aggregate so a mixed-model field can be built."""

    def __init__(self, by_text):
        self._by_text = by_text  # text -> (aggregate, model)

    def score_clip(self, text, duration_s=None, **kw):
        aggregate, model = self._by_text[text]
        return ScoredClip(
            aggregate=aggregate,
            sub_scores={},
            confidence=80,
            modalities_used=["text"],
            model_used=model,
            raw_usage={},
        )


def _recall(cands):
    def _fn(transcript, signals):
        return tuple(cands)

    return _fn


def test_select_clips_sorts_on_normalized_value_not_raw_aggregate(monkeypatch):
    # Generous lite group high, one stricter flash clip. On RAW aggregate the flash
    # 66 ranks last; with the per-model baselines wired (CLIP_MODEL_OFFSETS), the
    # flash clip must NOT be buried beneath the generous lite 70.
    monkeypatch.setenv("CLIP_MODEL_OFFSETS", '{"flash": 55.0}')
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c", "d", "e"))]
    by_text = {
        "a": (90.0, "lite"),
        "b": (88.0, "lite"),
        "c": (85.0, "lite"),
        "d": (70.0, "lite"),  # generous-model loser
        "e": (66.0, "flash"),  # stricter A/V finalist
    }
    out = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=_ModelScorer(by_text),
        quality_threshold=0.0,  # keep all — we assert ORDER
        tier=BUDGET,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
    ).clips
    titles = [c.candidate.title for c in out]
    # the flash clip (e) outranks the generous-model text clip (d)
    assert titles.index("e") < titles.index("d")
    # raw aggregate is preserved verbatim for display/billing (not overwritten by z)
    flash = next(c for c in out if c.candidate.title == "e")
    assert flash.scored.aggregate == 66.0
    # the normalized rank value is carried separately
    assert flash.rank_value != flash.scored.aggregate


def test_select_clips_preserves_raw_aggregate_for_single_model():
    # No cross-model mixing: ordering is exactly the raw-aggregate ordering and the
    # raw scores are carried verbatim.
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate(("a", "b", "c"))]
    by_text = {"a": (40.0, "lite"), "b": (90.0, "lite"), "c": (70.0, "lite")}
    out = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=_ModelScorer(by_text),
        quality_threshold=0.0,
        tier=BUDGET,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
    ).clips
    assert [c.candidate.title for c in out] == ["b", "c", "a"]
    assert [c.scored.aggregate for c in out] == [90.0, 70.0, 40.0]


def test_percentile_mode_keeps_top_fraction_not_an_absolute_cut():
    # 8 clips, p50 cut on the normalized distribution → roughly the top half clears
    # the bar (the floor for a 0s/empty transcript is MIN_FLOOR_CLIPS=3, inert here).
    cands = [_cand(t, i * 30, i * 30 + 20) for i, t in enumerate("abcdefgh")]
    by_text = {t: (float(50 + i * 5), "lite") for i, t in enumerate("abcdefgh")}
    out = select_clips(
        {},
        "v.mp4",
        recall_fn=_recall(cands),
        scorer=_ModelScorer(by_text),
        quality_threshold=999.0,  # would drop everything in ABSOLUTE mode...
        target_percentile=50.0,  # ...but percentile mode ignores it, keeps the top half
        tier=BUDGET,
        _signals_fn=lambda s: None,
        _cut_fn=_fake_cut,
        _score_fn=_serial_score,
    ).clips
    # the absolute 999 cut is bypassed: percentile keeps a real fraction, not zero.
    assert 3 <= len(out) <= 6
    # and the highest-raw clip ('h') is first (sorted on the monotone normalized value)
    assert out[0].candidate.title == "h"
