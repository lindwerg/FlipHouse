"""Unit coverage for clipping/preflight.py — the encoder probe is injected/patched."""

import logging

import pytest

from fliphouse_worker.clipping import preflight
from fliphouse_worker.clipping.preflight import assert_clip_codecs

_FULL = "V..... libvpx-vp9 ...\nA..... libopus ...\nV..... libx264 ...\n"


def test_assert_clip_codecs_passes_when_both_present():
    assert assert_clip_codecs(_run_fn=lambda: _FULL) is None


@pytest.mark.parametrize(
    "listing",
    [
        "A..... libopus ...\n",  # vp9 missing
        "V..... libvpx-vp9 ...\n",  # opus missing
        "V..... libx264 ...\n",  # both missing
    ],
)
def test_assert_clip_codecs_raises_when_missing(listing, caplog):
    with caplog.at_level(logging.CRITICAL), pytest.raises(RuntimeError):
        assert_clip_codecs(_run_fn=lambda: listing)
    assert any(r.levelno == logging.CRITICAL for r in caplog.records)


def test_probe_encoders_invokes_subprocess(monkeypatch):
    captured = {}

    class _Result:
        stdout = _FULL

    def fake_run(argv, **kwargs):
        captured["argv"] = argv
        captured["kwargs"] = kwargs
        return _Result()

    monkeypatch.setattr(preflight.subprocess, "run", fake_run)
    out = preflight._probe_encoders()

    assert out == _FULL
    assert captured["argv"] == ["ffmpeg", "-hide_banner", "-encoders"]
    assert captured["kwargs"]["text"] is True
