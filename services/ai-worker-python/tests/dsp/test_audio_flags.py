"""Unit coverage for dsp/audio_flags.py — synthetic PCM, no ffmpeg."""

import numpy as np
import pytest

from fliphouse_worker.dsp.audio_energy import SR
from fliphouse_worker.dsp.audio_flags import (
    AudioWindowFlags,
    HeuristicAudioTagger,
    classify_window,
    extract_audio_flags,
    harmonic_ratio,
    spectral_flatness,
    zero_crossing_rate,
)


def _pcm(samples: np.ndarray) -> bytes:
    return (np.clip(samples, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def _sine(freq: float, n: int, sr: int = SR) -> np.ndarray:
    return 0.6 * np.sin(2 * np.pi * freq * np.arange(n) / sr).astype(np.float32)


# ── spectral_flatness ─────────────────────────────────────────────────────


def test_spectral_flatness_high_for_white_noise():
    rng = np.random.default_rng(0)
    mag = np.abs(np.fft.rfft(rng.standard_normal(SR)))
    assert spectral_flatness(mag) > 0.2


def test_spectral_flatness_low_for_pure_tone():
    mag = np.abs(np.fft.rfft(_sine(440, SR)))
    assert spectral_flatness(mag) < 0.05


def test_spectral_flatness_empty_guard():
    assert spectral_flatness(np.zeros(0)) == 0.0


# ── zero_crossing_rate ────────────────────────────────────────────────────


def test_zcr_higher_for_noise_than_tone():
    rng = np.random.default_rng(1)
    assert zero_crossing_rate(rng.standard_normal(SR)) > zero_crossing_rate(_sine(120, SR))


def test_zcr_too_short_guard():
    assert zero_crossing_rate(np.zeros(1)) == 0.0


# ── harmonic_ratio ────────────────────────────────────────────────────────


def test_harmonic_ratio_high_for_periodic_tone():
    assert harmonic_ratio(_sine(200, SR), SR) > 0.5


def test_harmonic_ratio_empty_guard():
    assert harmonic_ratio(np.zeros(0), SR) == 0.0


def test_harmonic_ratio_zero_energy_guard():
    assert harmonic_ratio(np.zeros(SR, dtype=np.float32), SR) == 0.0


def test_harmonic_ratio_band_collapses_guard():
    # sr so small the F0 search band is empty (hi <= lo)
    assert harmonic_ratio(_sine(5, 32, sr=32), 32) == 0.0


# ── classify_window ────────────────────────────────────────────────────────


def test_classify_window_tonal_leans_music():
    flags = classify_window(t=1.0, zcr=0.1, flatness=0.02, harmonic_r=0.9)
    assert flags.music_conf > flags.applause_conf
    assert flags.t == 1.0


def test_classify_window_noisy_leans_applause():
    flags = classify_window(t=2.0, zcr=0.6, flatness=0.9, harmonic_r=0.1)
    assert flags.applause_conf > flags.music_conf


# ── tagger / extract ───────────────────────────────────────────────────────


def test_extract_audio_flags_per_window_count():
    flags = extract_audio_flags(_pcm(_sine(220, 3 * SR)))
    assert len(flags) == 3
    assert all(isinstance(f, AudioWindowFlags) for f in flags)


def test_extract_audio_flags_silence_window_zeroed():
    flags = extract_audio_flags(_pcm(np.zeros(SR, dtype=np.float32)))
    assert flags[0].music_conf == 0.0
    assert flags[0].laughter_conf == 0.0


def test_extract_audio_flags_empty_when_shorter_than_window():
    assert extract_audio_flags(_pcm(np.zeros(SR // 2, dtype=np.float32))) == ()


def test_extract_audio_flags_accepts_injected_tagger():
    sentinel = (AudioWindowFlags(0.0, 0.1, 0.2, 0.3, 0.4),)

    class FakeTagger:
        def tag(self, pcm, sr):
            return sentinel

    assert extract_audio_flags(b"\x00\x00", tagger=FakeTagger()) is sentinel


def test_heuristic_tagger_default_sr():
    tagger = HeuristicAudioTagger()
    assert tagger.tag(_pcm(_sine(330, SR))) != ()


def test_audio_window_flags_frozen():
    f = AudioWindowFlags(0.0, 0.0, 0.0, 0.0, 0.0)
    with pytest.raises(AttributeError):
        f.t = 1.0  # type: ignore[misc]
