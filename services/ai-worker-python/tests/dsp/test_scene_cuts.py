"""Unit coverage for dsp/scene_cuts.py — frozen golden scdet text / mocked subprocess.

GOLDEN_SCDET is the real ffmpeg-8.1 ``scdet,metadata=print`` stdout captured from
a 3-shot fixture: per detected frame a ``score`` line precedes a ``time`` line.
"""

import subprocess

import pytest

from fliphouse_worker.dsp import scene_cuts as sc
from fliphouse_worker.dsp.scene_cuts import (
    CUT_SCORE_FLOOR,
    SceneCut,
    extract_scene_cuts,
    parse_cuts,
)

GOLDEN_SCDET = """\
frame:0    pts:30720   pts_time:2
lavfi.scd.mafd=26.692
lavfi.scd.score=26.463
lavfi.scd.time=2
frame:1    pts:61440   pts_time:4
lavfi.scd.mafd=20.568
lavfi.scd.score=20.568
lavfi.scd.time=4
"""


def test_parse_cuts_above_floor():
    cuts = parse_cuts(GOLDEN_SCDET)
    assert cuts == (
        SceneCut(time_s=2.0, score=26.463),
        SceneCut(time_s=4.0, score=20.568),
    )


def test_parse_cuts_drops_below_floor():
    weak = "lavfi.scd.score=3.100\nlavfi.scd.time=1.5\n"
    assert parse_cuts(weak) == ()
    assert CUT_SCORE_FLOOR > 3.1  # documents the floor that dropped it


def test_parse_cuts_time_without_pending_score_is_skipped():
    # a stray time line with no preceding score must not crash or emit
    assert parse_cuts("lavfi.scd.time=9.0\n") == ()


def test_parse_cuts_empty_output():
    assert parse_cuts("") == ()


def test_parse_cuts_custom_floor_keeps_weak_cut():
    weak = "lavfi.scd.score=3.100\nlavfi.scd.time=1.5\n"
    assert parse_cuts(weak, score_floor=1.0) == (SceneCut(time_s=1.5, score=3.1),)


def test_extract_scene_cuts_uses_injected_seam():
    captured = {}

    def fake_run(src):
        captured["src"] = src
        return GOLDEN_SCDET

    cuts = extract_scene_cuts("clip.mp4", _run_fn=fake_run)
    assert captured["src"] == "clip.mp4"
    assert len(cuts) == 2


def test_run_video_ffmpeg_invokes_subprocess(monkeypatch):
    class FakeCompleted:
        stdout = GOLDEN_SCDET.encode("utf-8")

    seen = {}

    def fake_run(cmd, check, capture_output):
        seen["cmd"] = cmd
        seen["check"] = check
        return FakeCompleted()

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    out = sc._run_video_ffmpeg("in.mp4")
    assert "lavfi.scd.score" in out
    assert seen["check"] is True
    assert any("scdet" in str(part) for part in seen["cmd"])


def test_run_video_ffmpeg_propagates_error(monkeypatch):
    def fake_run(cmd, check, capture_output):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(sc.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        sc._run_video_ffmpeg("in.mp4")
