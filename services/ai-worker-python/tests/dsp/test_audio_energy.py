"""Unit coverage for dsp/audio_energy.py — synthetic numpy arrays / mocked subprocess."""

import subprocess

import numpy as np
import pytest

from fliphouse_worker.dsp import audio_energy as ae
from fliphouse_worker.dsp.audio_energy import (
    HOP,
    SR,
    AudioEnergy,
    Pause,
    audio_energy_from_pcm,
    decode_pcm,
    detect_energy_peaks,
    detect_pauses,
    energy_envelope,
    extract_audio_energy,
)


def _pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


# ── decode_pcm ────────────────────────────────────────────────────────────


def test_decode_pcm_int16_to_float_minus1_plus1():
    raw = np.array([0, 16384, -16384], dtype="<i2").tobytes()
    out = decode_pcm(raw)
    assert out.dtype == np.float32
    np.testing.assert_allclose(out, [0.0, 0.5, -0.5], atol=1e-4)


def test_decode_pcm_drops_odd_trailing_byte():
    raw = np.array([100, 200], dtype="<i2").tobytes() + b"\x07"
    out = decode_pcm(raw)
    assert len(out) == 2  # the dangling byte is sliced off, no ValueError


# ── energy_envelope ─────────────────────────────────────────────────────────


def test_energy_envelope_shape_and_time_axis():
    x = np.ones(3 * HOP, dtype=np.float32)
    env = energy_envelope(x)
    assert len(env.t) == len(env.rms) == len(env.dbfs) == 3
    np.testing.assert_allclose(env.t, [0.0, HOP / SR, 2 * HOP / SR])
    np.testing.assert_allclose(env.rms, 1.0, atol=1e-6)


def test_energy_envelope_truncates_partial_window():
    x = np.ones(2 * HOP + 17, dtype=np.float32)
    assert len(energy_envelope(x).rms) == 2  # the 17 trailing samples are dropped


def test_energy_envelope_empty_when_shorter_than_hop():
    env = energy_envelope(np.ones(HOP - 1, dtype=np.float32))
    assert len(env.t) == 0 and len(env.rms) == 0 and len(env.dbfs) == 0


def test_energy_envelope_silence_clamps_to_eps_not_log_zero():
    env = energy_envelope(np.zeros(HOP, dtype=np.float32))
    assert np.isfinite(env.dbfs).all() and env.dbfs[0] < -100  # ~-200 dBFS, not -inf


# ── detect_energy_peaks ──────────────────────────────────────────────────────


def test_detect_energy_peaks_finds_local_burst():
    dbfs = np.full(41, -50.0)
    dbfs[20] = -5.0  # one loud window in the middle, well above its neighborhood
    t = np.arange(41) * (HOP / SR)
    assert detect_energy_peaks(t, dbfs) == (pytest.approx(20 * HOP / SR),)


def test_detect_energy_peaks_none_on_uniform():
    # constant loudness → no window clears its local median by the margin
    assert detect_energy_peaks(np.arange(41) * (HOP / SR), np.full(41, -30.0)) == ()


def test_detect_energy_peaks_collapses_close_bursts():
    dbfs = np.full(41, -50.0)
    dbfs[20] = dbfs[22] = -5.0  # 0.2 s apart, under MIN_PEAK_DIST_S → kept as one
    t = np.arange(41) * (HOP / SR)
    peaks = detect_energy_peaks(t, dbfs)
    assert len(peaks) == 1 and peaks[0] == pytest.approx(20 * HOP / SR)


def test_detect_energy_peaks_empty_input():
    assert detect_energy_peaks(np.zeros(0), np.zeros(0)) == ()


# ── detect_pauses ────────────────────────────────────────────────────────────


def test_detect_pauses_keeps_long_run_drops_short_run():
    # windows 0-1 quiet (0.2s < 0.4 → dropped), 2-3 loud, 4-9 quiet (0.6s ≥ 0.4 → kept)
    dbfs = np.array([-60, -60, -10, -10, -60, -60, -60, -60, -60, -60.0])
    t = np.arange(10) * (HOP / SR)
    pauses = detect_pauses(t, dbfs)
    assert len(pauses) == 1
    assert pauses[0].start == pytest.approx(0.4)
    assert pauses[0].end == pytest.approx(1.0)


def test_detect_pauses_empty_when_no_silence():
    assert detect_pauses(np.arange(5) * 0.1, np.full(5, -10.0)) == ()


def test_detect_pauses_empty_input():
    assert detect_pauses(np.zeros(0), np.zeros(0)) == ()


# ── Pause dataclass ──────────────────────────────────────────────────────────


def test_pause_mid_and_frozen():
    p = Pause(start=2.0, end=4.0)
    assert p.mid == 3.0
    with pytest.raises(AttributeError):
        p.start = 9.0  # type: ignore[misc]


# ── composition + seam ───────────────────────────────────────────────────────


def _tone(amp: float, seconds: float) -> np.ndarray:
    n = int(SR * seconds)
    return (amp * np.sin(2 * np.pi * 220 * np.arange(n) / SR)).astype(np.float32)


def test_audio_energy_from_pcm_integration():
    # 1 s silence, quiet speech-like tone, a loud BURST in the middle, quiet tone again.
    # The burst is a local energy peak; the silence is a dramatic pause.
    signal = np.concatenate(
        [np.zeros(SR, dtype=np.float32), _tone(0.05, 1.0), _tone(0.9, 0.3), _tone(0.05, 1.0)]
    )
    result = audio_energy_from_pcm(_pcm(signal))
    assert isinstance(result, AudioEnergy)
    assert len(result.pauses) >= 1  # the 1 s silence
    assert len(result.peaks_s) >= 1  # the loud burst stands out from the quiet tone


def test_extract_audio_energy_uses_injected_seam():
    raw = _pcm(np.zeros(2 * SR, dtype=np.float32))
    captured = {}

    def fake_run(src):
        captured["src"] = src
        return raw

    result = extract_audio_energy("video.mp4", _run_fn=fake_run)
    assert captured["src"] == "video.mp4"
    assert len(result.pauses) >= 1


def test_run_audio_ffmpeg_invokes_subprocess(monkeypatch):
    class FakeCompleted:
        stdout = b"PCMBYTES"

    seen = {}

    def fake_run(cmd, check, capture_output):
        seen["cmd"] = cmd
        seen["check"] = check
        return FakeCompleted()

    monkeypatch.setattr(ae.subprocess, "run", fake_run)
    assert ae._run_audio_ffmpeg("in.mp4") == b"PCMBYTES"
    assert seen["check"] is True
    assert "in.mp4" in seen["cmd"]


def test_run_audio_ffmpeg_propagates_called_process_error(monkeypatch):
    def fake_run(cmd, check, capture_output):
        raise subprocess.CalledProcessError(1, cmd)

    monkeypatch.setattr(ae.subprocess, "run", fake_run)
    with pytest.raises(subprocess.CalledProcessError):
        ae._run_audio_ffmpeg("in.mp4")
