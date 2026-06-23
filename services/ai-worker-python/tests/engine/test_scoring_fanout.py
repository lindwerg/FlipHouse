"""Unit coverage for engine/scoring_fanout.py — cut/scorer seams faked, map serial."""

import logging
import subprocess

import pytest

from fliphouse_worker.clipping import CLIP_VIDEO_MIME, ClipTooLargeError
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import (
    ClipScore,
    DegradationCounts,
    DegradationReason,
    _score_one,
    _threadpool_map,
    count_degradations,
    score_candidates,
)
from fliphouse_worker.scoring import ScoredClip
from fliphouse_worker.scoring.tiers import BUDGET, AvScope, TierConfig


def _finalists_tier(n):
    return TierConfig(
        name="t",
        av_scope=AvScope.FINALISTS,
        escalate=False,
        escalation_profile=None,
        av_finalists_n=n,
    )


class _FakeAPIError(Exception):
    """Stands in for openai.APIError — proves the BROAD except catches non-narrow types."""


def _cand(title, start, end, text=None):
    return CandidateClip(title, start, end, 50.0, 0.0, text or title)


def _scored(agg, modalities):
    return ScoredClip(agg, {}, 80, modalities, "fake", {})


def _serial(fn, items):
    return [fn(i) for i in items]


class RecordingScorer:
    """Records every score_clip call; returns a fixed aggregate."""

    def __init__(self, aggregate=70.0):
        self.calls = []
        self._aggregate = aggregate

    def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
        self.calls.append(
            {"text": text, "duration_s": duration_s, "video": video, "video_mime": video_mime}
        )
        modalities = ["text", "visual", "audio"] if video is not None else ["text"]
        return _scored(self._aggregate, modalities)


class RaiseOnVideoScorer:
    """Raises ``exc`` on the A/V call (video set); text-only call succeeds."""

    def __init__(self, exc):
        self._exc = exc
        self.text_calls = 0

    def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
        if video is not None:
            raise self._exc
        self.text_calls += 1
        return _scored(55.0, ["text"])


class DeadScorer:
    """Fails on BOTH modalities."""

    def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
        raise RuntimeError("boom")


def test_av_path_scores_with_video():
    scorer = RecordingScorer()
    cand = _cand("a", 10.0, 55.0, "hook text")
    out = _score_one(cand, scorer, "v.mp4", lambda s, a, b: b"WEBM")
    assert isinstance(out, ClipScore) and out.used_video is True
    call = scorer.calls[0]
    assert call["video"] == b"WEBM" and call["video_mime"] == CLIP_VIDEO_MIME
    assert call["duration_s"] == 45.0


def test_falls_back_to_text_on_clip_too_large():
    scorer = RecordingScorer()

    def cut(s, a, b):
        raise ClipTooLargeError("too big")

    out = _score_one(_cand("a", 0.0, 30.0), scorer, "v.mp4", cut)
    assert out.used_video is False
    assert scorer.calls[0]["video"] is None  # text-only fallback


@pytest.mark.parametrize(
    "exc",
    [subprocess.CalledProcessError(1, "ffmpeg"), OSError("no ffmpeg")],
)
def test_falls_back_on_called_process_error_and_oserror(exc):
    scorer = RecordingScorer()

    def cut(s, a, b):
        raise exc

    out = _score_one(_cand("a", 0.0, 30.0), scorer, "v.mp4", cut)
    assert out.used_video is False


def test_falls_back_to_text_on_av_scorer_value_error():
    scorer = RaiseOnVideoScorer(ValueError("bad json"))
    out = _score_one(_cand("a", 0.0, 30.0), scorer, "v.mp4", lambda s, a, b: b"WEBM")
    assert out.used_video is False and scorer.text_calls == 1


def test_falls_back_to_text_on_runtime_error():
    # RuntimeError is what the adapter raises on 402 / retries exhausted — the
    # critical blocker the broad catch fixes.
    scorer = RaiseOnVideoScorer(RuntimeError("402 out of credits"))
    out = _score_one(_cand("a", 0.0, 30.0), scorer, "v.mp4", lambda s, a, b: b"WEBM")
    assert out.used_video is False


def test_falls_back_to_text_on_api_error():
    scorer = RaiseOnVideoScorer(_FakeAPIError("5xx"))
    out = _score_one(_cand("a", 0.0, 30.0), scorer, "v.mp4", lambda s, a, b: b"WEBM")
    assert out.used_video is False


def test_drops_clip_when_both_modalities_fail(caplog):
    with caplog.at_level(logging.WARNING):
        out = score_candidates(
            [_cand("a", 0.0, 30.0)],
            DeadScorer(),
            "v.mp4",
            cut_fn=lambda s, a, b: b"WEBM",
            _map_fn=_serial,
        )
    assert out == []
    assert any("both modalities failed" in r.message for r in caplog.records)
    assert any("dropped" in r.message for r in caplog.records)


def test_one_bad_clip_keeps_rest():
    cands = [_cand("a", 0.0, 20.0), _cand("dead", 30.0, 50.0), _cand("c", 60.0, 80.0)]

    class _MixedScorer:
        def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
            if text == "dead":
                raise RuntimeError("boom")
            return _scored(70.0, ["text", "visual", "audio"] if video else ["text"])

    out = score_candidates(
        cands, _MixedScorer(), "v.mp4", cut_fn=lambda s, a, b: b"WEBM", _map_fn=_serial
    )
    assert [cs.candidate.title for cs in out] == ["a", "c"]


def test_threadpool_map_empty_returns_list():
    called = []
    assert _threadpool_map(lambda x: called.append(x), []) == []
    assert called == []  # no executor constructed, fn never called


def test_threadpool_map_executes_joins_and_clamps():
    assert _threadpool_map(lambda x: x * 2, [1, 2]) == [2, 4]  # order preserved, min-clamp path


def test_threadpool_map_isolates_unanticipated_exception(caplog):
    def fn(x):
        if x == 1:
            raise RuntimeError("unexpected")
        return x

    with caplog.at_level(logging.WARNING):
        out = _threadpool_map(fn, [1, 2])
    assert out == [None, 2]
    assert any("task crashed" in r.message for r in caplog.records)


def test_threadpool_map_max_workers_clamp_below_item_count():
    # workers < items: all still processed, order preserved.
    assert _threadpool_map(lambda x: x * 2, [1, 2, 3], max_workers=1) == [2, 4, 6]


# ── tier A/V scope (P2-S7) ───────────────────────────────────────────────


def _cut_counting():
    calls = []

    def cut(src, start, end):
        calls.append((start, end))
        return b"WEBM"

    return cut, calls


def test_tier_budget_scores_text_only_never_cuts():
    cut, calls = _cut_counting()
    scorer = RecordingScorer()
    out = score_candidates(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        scorer,
        "v.mp4",
        cut_fn=cut,
        _map_fn=_serial,
        tier=BUDGET,
    )
    assert calls == []  # never cut
    assert all(cs.used_video is False for cs in out)
    assert all(c["video"] is None for c in scorer.calls)


def test_tier_finalists_av_top_n_only():
    cut, calls = _cut_counting()
    cands = [_cand("a", 0, 20), _cand("b", 30, 50), _cand("c", 60, 80)]
    out = score_candidates(
        cands, RecordingScorer(), "v.mp4", cut_fn=cut, _map_fn=_serial, tier=_finalists_tier(1)
    )
    assert len(calls) == 1  # only the top finalist cut
    used = {cs.candidate.title: cs.used_video for cs in out}
    assert used == {"a": True, "b": False, "c": False}


def test_tier_finalists_n_zero_all_text():
    cut, calls = _cut_counting()
    out = score_candidates(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        RecordingScorer(),
        "v.mp4",
        cut_fn=cut,
        _map_fn=_serial,
        tier=_finalists_tier(0),
    )
    assert calls == [] and all(cs.used_video is False for cs in out)


def test_tier_finalists_n_ge_len_all_av():
    cut, calls = _cut_counting()
    out = score_candidates(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        RecordingScorer(),
        "v.mp4",
        cut_fn=cut,
        _map_fn=_serial,
        tier=_finalists_tier(9),
    )
    assert len(calls) == 2 and all(cs.used_video is True for cs in out)


def test_score_one_want_video_false_scores_text_only():
    cut, calls = _cut_counting()
    scorer = RecordingScorer()
    out = _score_one(_cand("a", 0, 30), scorer, "v.mp4", cut, want_video=False)
    assert out.used_video is False and calls == []
    assert scorer.calls[0]["video"] is None


def test_score_one_want_video_false_drops_on_text_failure():
    out = _score_one(
        _cand("a", 0, 30), DeadScorer(), "v.mp4", lambda s, a, b: b"WEBM", want_video=False
    )
    assert out is None


def test_default_threadpool_map_applies_tier_worker_cap():
    # Default _map_fn → the partial-wrapped threadpool branch is exercised.
    out = score_candidates(
        [_cand("a", 0, 20)], RecordingScorer(), "v.mp4", cut_fn=lambda s, a, b: b"WEBM", tier=BUDGET
    )
    assert len(out) == 1 and out[0].used_video is False


# ── degradation reasons / counters (ASK #7 part c) ───────────────────────────


class TextOnlyDespiteVideoScorer:
    """Scores the clip WITH video attached but reports text-only modalities (#3)."""

    def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
        # video IS attached, yet the model claims it only assessed text — the silent
        # degradation aggregate.py's dual gate would otherwise count as plain text.
        return _scored(60.0, ["text"])


def test_av_success_reason_is_av_ok():
    out = _score_one(_cand("a", 0, 30), RecordingScorer(), "v.mp4", lambda s, a, b: b"WEBM")
    assert out.used_video is True
    assert out.reason is DegradationReason.AV_OK


def test_av_failure_reason_is_av_failed_text():
    scorer = RaiseOnVideoScorer(RuntimeError("402"))
    out = _score_one(_cand("a", 0, 30), scorer, "v.mp4", lambda s, a, b: b"WEBM")
    assert out.used_video is False
    assert out.reason is DegradationReason.AV_FAILED_TEXT  # a REAL failure, not a budget skip


def test_budget_skip_reason_is_want_none():
    out = _score_one(
        _cand("a", 0, 30), RecordingScorer(), "v.mp4", lambda s, a, b: b"WEBM", want_video=False
    )
    assert out.used_video is False
    assert out.reason is DegradationReason.WANT_NONE


def test_modality_dropped_reason_when_model_reports_text_only(caplog):
    with caplog.at_level(logging.WARNING):
        out = _score_one(
            _cand("a", 0, 30), TextOnlyDespiteVideoScorer(), "v.mp4", lambda s, a, b: b"WEBM"
        )
    assert out.used_video is True  # the clip WAS sent with video
    assert out.reason is DegradationReason.MODALITY_DROPPED
    assert any("no video/audio modality" in r.message for r in caplog.records)


def test_modality_dropped_audio_only_counts_as_av_ok():
    # audio is an A/V modality — a clip the model assessed for audio is NOT dropped.
    class _AudioOnly:
        def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
            return _scored(60.0, ["text", "audio"])

    out = _score_one(_cand("a", 0, 30), _AudioOnly(), "v.mp4", lambda s, a, b: b"WEBM")
    assert out.reason is DegradationReason.AV_OK


def test_count_degradations_distinguishes_the_three_text_degradations():
    cands = [_cand("ok", 0, 20), _cand("fail", 30, 50), _cand("drop", 60, 80)]

    class _Mixed:
        def score_clip(self, text, duration_s=None, *, video=None, video_mime=None):
            if text == "fail" and video is not None:
                raise RuntimeError("ffmpeg-ish")
            if text == "drop":
                return _scored(60.0, ["text"])  # video sent, modalities dropped
            return _scored(70.0, ["text", "video"] if video else ["text"])

    out = score_candidates(
        cands,
        _Mixed(),
        "v.mp4",
        cut_fn=lambda s, a, b: b"WEBM",
        _map_fn=_serial,
        tier=_finalists_tier(9),
    )
    counts = count_degradations(out)
    assert counts.av_succeeded == 1  # "ok"
    assert counts.av_failed_fellback == 1  # "fail" fell back to text
    assert counts.modalities_dropped == 1  # "drop"
    assert counts.budget_skipped == 0
    # the four buckets account for every survivor exactly once
    total = (
        counts.av_succeeded
        + counts.av_failed_fellback
        + counts.modalities_dropped
        + counts.budget_skipped
    )
    assert total == len(out)


def test_count_degradations_budget_tier_all_want_none():
    out = score_candidates(
        [_cand("a", 0, 20), _cand("b", 30, 50)],
        RecordingScorer(),
        "v.mp4",
        cut_fn=lambda s, a, b: b"WEBM",
        _map_fn=_serial,
        tier=BUDGET,
    )
    counts = count_degradations(out)
    assert counts == DegradationCounts(budget_skipped=2)


def test_degradation_counts_default_is_all_zero():
    assert count_degradations([]) == DegradationCounts(0, 0, 0, 0)
