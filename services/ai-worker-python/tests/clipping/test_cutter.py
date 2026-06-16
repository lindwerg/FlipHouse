"""Unit coverage for clipping/cutter.py — the ffmpeg seam is injected/patched."""

import logging

import pytest

from fliphouse_worker.clipping import cutter
from fliphouse_worker.clipping.cutter import (
    FS_LIMIT,
    MAX_CLIP_BYTES,
    ClipTooLargeError,
    _fs_bytes,
    cut_clip,
)


def test_cut_clip_uses_injected_seam_returns_bytes():
    calls = []

    def fake_run(src, start, end):
        calls.append((src, start, end))
        return b"WEBMBYTES"

    out = cut_clip("v.mp4", 10.0, 55.0, _run_fn=fake_run)
    assert out == b"WEBMBYTES"
    assert calls == [("v.mp4", 10.0, 55.0)]


def test_cut_clip_raises_when_over_cap():
    def fake_run(src, start, end):
        return b"x" * (MAX_CLIP_BYTES + 1)

    with pytest.raises(ClipTooLargeError):
        cut_clip("v.mp4", 0.0, 30.0, _run_fn=fake_run)


def test_cut_clip_rejects_non_positive_span():
    invoked = []

    def recording_run(src, start, end):
        invoked.append((src, start, end))
        return b""

    with pytest.raises(ValueError):
        cut_clip("v.mp4", 30.0, 30.0, _run_fn=recording_run)
    assert invoked == []  # the seam must NOT run for an invalid span


def test_cut_clip_warns_on_near_fs_limit(caplog):
    near = int(0.98 * _fs_bytes(FS_LIMIT))

    with caplog.at_level(logging.WARNING):
        out = cut_clip("v.mp4", 0.0, 50.0, _run_fn=lambda s, a, b: b"x" * near)
    assert len(out) == near
    assert any("truncated" in r.message or "partial view" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        cut_clip("v.mp4", 0.0, 5.0, _run_fn=lambda s, a, b: b"tiny")
    assert caplog.records == []  # small clips log nothing


def test_run_clip_ffmpeg_builds_expected_argv(monkeypatch):
    captured = {}

    class _Result:
        stdout = b"webm-bytes"

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(cutter.subprocess, "run", fake_run)
    out = cutter._run_clip_ffmpeg("src.mp4", 12.0, 57.0)

    assert out == b"webm-bytes"
    argv = captured["argv"]
    assert argv.index("-ss") < argv.index("-i")
    for token in ("libvpx-vp9", "libopus", "-crf", "34", "-fs", "9M", "-f", "webm", "pipe:1"):
        assert token in argv
    assert "scale=-2:480,fps=15" in argv
    assert argv[argv.index("-t") + 1] == f"{57.0 - 12.0}"
    assert captured["kwargs"]["check"] is True
    assert captured["kwargs"]["capture_output"] is True


def test_fs_limit_invariant_holds():
    # Documents the only condition under which ClipTooLargeError can fire from
    # the real path: it cannot, because -fs caps the output below the inline cap.
    assert _fs_bytes(FS_LIMIT) <= MAX_CLIP_BYTES


def test_fs_bytes_parses_plain_integer():
    assert _fs_bytes("4096") == 4096
