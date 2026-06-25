"""Unit coverage for clipping/cutter.py — the ffmpeg seam is injected/patched."""

import logging

import pytest

from fliphouse_worker.clipping import cutter
from fliphouse_worker.clipping.cutter import (
    DEFAULT_FINALIST_PRESET,
    MAX_CLIP_BYTES,
    SAFE_FINALIST_PRESET,
    ClipTooLargeError,
    FinalistPreset,
    _fs_bytes,
    cut_clip,
    target_video_bitrate_bps,
)


def test_cut_clip_uses_injected_seam_returns_bytes():
    calls = []

    def fake_run(src, start, end, *, preset):
        calls.append((src, start, end, preset))
        return b"WEBMBYTES"

    out = cut_clip("v.mp4", 10.0, 55.0, _run_fn=fake_run)
    assert out == b"WEBMBYTES"
    assert calls == [("v.mp4", 10.0, 55.0, DEFAULT_FINALIST_PRESET)]


def test_cut_clip_raises_when_over_cap():
    def fake_run(src, start, end, *, preset):
        return b"x" * (MAX_CLIP_BYTES + 1)

    with pytest.raises(ClipTooLargeError):
        cut_clip("v.mp4", 0.0, 30.0, _run_fn=fake_run)


def test_cut_clip_rejects_non_positive_span():
    invoked = []

    def recording_run(src, start, end, *, preset):
        invoked.append((src, start, end))
        return b""

    with pytest.raises(ValueError):
        cut_clip("v.mp4", 30.0, 30.0, _run_fn=recording_run)
    assert invoked == []  # the seam must NOT run for an invalid span


def test_cut_clip_warns_on_near_fs_limit(caplog):
    near = int(0.98 * _fs_bytes(DEFAULT_FINALIST_PRESET.fs_limit))

    with caplog.at_level(logging.WARNING):
        out = cut_clip("v.mp4", 0.0, 50.0, _run_fn=lambda s, a, b, *, preset: b"x" * near)
    assert len(out) == near
    assert any("truncated" in r.message or "partial view" in r.message for r in caplog.records)

    caplog.clear()
    with caplog.at_level(logging.WARNING):
        cut_clip("v.mp4", 0.0, 5.0, _run_fn=lambda s, a, b, *, preset: b"tiny")
    assert caplog.records == []  # small clips log nothing


def test_cut_clip_honors_injected_preset():
    seen = {}

    def fake_run(src, start, end, *, preset):
        seen["preset"] = preset
        return b"WEBM"

    cut_clip("v.mp4", 0.0, 30.0, preset=SAFE_FINALIST_PRESET, _run_fn=fake_run)
    assert seen["preset"] is SAFE_FINALIST_PRESET


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
    # MMV-2: -b:v carries the duration-aware average-bitrate cap (no longer "0").
    bv = argv[argv.index("-b:v") + 1]
    assert bv != "0"
    assert int(bv) == target_video_bitrate_bps(57.0 - 12.0, preset=DEFAULT_FINALIST_PRESET)
    assert captured["kwargs"]["check"] is True
    assert captured["kwargs"]["capture_output"] is True


def test_run_clip_ffmpeg_safe_preset_compresses_under_cap(monkeypatch):
    captured = {}

    class _Result:
        stdout = b"tiny-webm"

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        return _Result()

    monkeypatch.setattr(cutter.subprocess, "run", fake_run)
    cutter._run_clip_ffmpeg("src.mp4", 0.0, 50.0, preset=SAFE_FINALIST_PRESET)

    argv = captured["argv"]
    # Tighter knobs: lower res/fps/quality + a smaller -fs budget than the default.
    assert "scale=-2:360,fps=12" in argv
    for token in ("-crf", "37", "-fs", "6M", "-b:a", "24k"):
        assert token in argv
    # The finalist compression sizing assertion: the SAFE budget is comfortably
    # under the OpenRouter inline cap, so the clip fits WITHOUT -fs truncation.
    assert _fs_bytes(SAFE_FINALIST_PRESET.fs_limit) <= MAX_CLIP_BYTES
    assert _fs_bytes(SAFE_FINALIST_PRESET.fs_limit) < _fs_bytes(DEFAULT_FINALIST_PRESET.fs_limit)


def test_every_preset_fs_limit_under_cap():
    # The generalized build-time guard: EVERY defined preset's -fs cap stays below
    # the inline cap, so the real ffmpeg path can never emit an over-cap clip.
    for preset in (DEFAULT_FINALIST_PRESET, SAFE_FINALIST_PRESET):
        assert _fs_bytes(preset.fs_limit) <= MAX_CLIP_BYTES


def test_finalist_preset_is_frozen():
    import dataclasses

    with pytest.raises(dataclasses.FrozenInstanceError):
        DEFAULT_FINALIST_PRESET.crf = 99  # type: ignore[misc]


def test_finalist_preset_is_constructible():
    p = FinalistPreset(scale="scale=-2:240", fps=10, crf=40, audio_bitrate="16k", fs_limit="3M")
    assert p.fps == 10 and p.fs_limit == "3M"


def test_fs_bytes_parses_plain_integer():
    assert _fs_bytes("4096") == 4096


# ── MMV-2: duration-aware encode keeps long finalists UNDER the cap ──────────


def test_target_bitrate_scales_inversely_with_duration():
    # A longer clip MUST get a lower average bitrate so its whole-clip byte total
    # still fits the same -fs budget (the old CRF-only sizing ignored duration).
    b50 = target_video_bitrate_bps(50.0, preset=SAFE_FINALIST_PRESET)
    b120 = target_video_bitrate_bps(120.0, preset=SAFE_FINALIST_PRESET)
    b180 = target_video_bitrate_bps(180.0, preset=SAFE_FINALIST_PRESET)
    assert b50 > b120 > b180 > 0


def test_target_bitrate_fits_under_fs_cap_across_durations():
    # For every finalist duration the encoded average bitrate × duration lands the
    # WHOLE clip's video stream under the -fs budget — so no -fs truncation, no
    # corrupt tail, no silent text fallback (the MMV-2 invariant).
    cap_bytes = _fs_bytes(SAFE_FINALIST_PRESET.fs_limit)
    for duration in (50.0, 120.0, 180.0):
        bps = target_video_bitrate_bps(duration, preset=SAFE_FINALIST_PRESET)
        encoded_video_bytes = bps * duration / 8
        # Strictly under the cap (the 0.85 fraction reserves audio + container room).
        assert encoded_video_bytes < cap_bytes
        assert encoded_video_bytes <= cap_bytes * 0.85 + 1


def test_target_bitrate_fails_closed_on_non_positive_duration():
    # cut_clip guards a non-positive span upstream, but the helper must still return
    # a valid positive bitrate (never 0 / negative) so ffmpeg's -b:v is well-formed.
    assert target_video_bitrate_bps(0.0, preset=SAFE_FINALIST_PRESET) > 0
    assert target_video_bitrate_bps(-5.0, preset=SAFE_FINALIST_PRESET) > 0


def test_long_finalist_argv_carries_a_lower_bitrate_than_a_short_one(monkeypatch):
    captured = []

    class _Result:
        stdout = b"webm"

    def fake_run(argv, **kwargs):
        captured.append(argv)
        return _Result()

    monkeypatch.setattr(cutter.subprocess, "run", fake_run)
    cutter._run_clip_ffmpeg("src.mp4", 0.0, 50.0, preset=SAFE_FINALIST_PRESET)
    cutter._run_clip_ffmpeg("src.mp4", 0.0, 180.0, preset=SAFE_FINALIST_PRESET)

    short_bps = int(captured[0][captured[0].index("-b:v") + 1])
    long_bps = int(captured[1][captured[1].index("-b:v") + 1])
    assert long_bps < short_bps
