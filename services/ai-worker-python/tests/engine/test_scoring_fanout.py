"""Unit coverage for engine/scoring_fanout.py — cut/scorer seams faked, map serial."""

import logging
import subprocess

import pytest

from fliphouse_worker.clipping import CLIP_VIDEO_MIME, ClipTooLargeError
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.engine.scoring_fanout import (
    ClipScore,
    _score_one,
    _threadpool_map,
    score_candidates,
)
from fliphouse_worker.scoring import ScoredClip


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
