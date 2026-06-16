"""Unit coverage for dsp/local_signals.py — both ffmpeg seams injected as fakes."""

import numpy as np
import pytest

from fliphouse_worker.dsp.audio_energy import SR, Pause
from fliphouse_worker.dsp.local_signals import LocalSignals, extract_local_signals
from fliphouse_worker.dsp.scene_cuts import SceneCut

_GOLDEN_CUT = "lavfi.scd.score=26.463\nlavfi.scd.time=2\n"


def _pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _signal() -> bytes:
    quiet = np.zeros(2 * SR, dtype=np.float32)
    tone = 0.7 * np.sin(np.linspace(0, 600 * np.pi, SR)).astype(np.float32)
    return _pcm(np.concatenate([quiet, tone]))


def test_extract_local_signals_bundles_all_signals():
    raw = _signal()
    signals = extract_local_signals(
        "src.mp4",
        _run_audio_fn=lambda src: raw,
        _run_video_fn=lambda src: _GOLDEN_CUT,
    )
    assert isinstance(signals, LocalSignals)
    assert signals.scene_cuts == (SceneCut(time_s=2.0, score=26.463),)
    assert len(signals.pauses) >= 1
    assert all(isinstance(p, Pause) for p in signals.pauses)
    assert len(signals.audio_flags) >= 1


def test_extract_local_signals_forwards_src_to_both_seams():
    seen = {}

    def fake_audio(src):
        seen["audio"] = src
        return _pcm(np.zeros(SR, dtype=np.float32))

    def fake_video(src):
        seen["video"] = src
        return ""

    extract_local_signals("v.mp4", _run_audio_fn=fake_audio, _run_video_fn=fake_video)
    assert seen == {"audio": "v.mp4", "video": "v.mp4"}


def test_local_signals_is_frozen():
    signals = LocalSignals(pauses=(), energy_peaks_s=(), scene_cuts=(), audio_flags=())
    with pytest.raises(AttributeError):
        signals.pauses = (Pause(0.0, 1.0),)  # type: ignore[misc]
