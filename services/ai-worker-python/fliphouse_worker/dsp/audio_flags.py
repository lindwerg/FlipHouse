"""Stage 0 audio-event flags (P2-S5): coarse laughter / music / applause / speech.

A cheap, deterministic, pure-numpy heuristic over 1 s windows — spectral
flatness (tonal vs noise-like), FFT-based harmonic ratio (voiced/musical
periodicity), and zero-crossing rate. The laughter/music/applause confidences
feed Stage A recall as a small boost (a clip over a laugh, a music sting, or
applause is more clip-worthy); ``speech_conf`` is informational. None are rubric
inputs, so coarse is fine.

# PHASE3-GPU: a real audio tagger (YAMNet / PANNs ONNX) is the future upgrade —
inject it via ``extract_audio_flags(..., tagger=...)``; any object with a
``tag(pcm, sr)`` method works. We ship no ONNX weights in S5: a bundled model
under the 100 % coverage gate would force mocking onnxruntime, which is coverage
theater, and the heuristic is enough for a boost signal.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

import numpy as np

from .audio_energy import EPS, SILENCE_DBFS, SR, decode_pcm

FLAG_WIN_S = 1.0  # classification window (s)
SILENCE_RMS = 10.0 ** (SILENCE_DBFS / 20.0)  # linear RMS below which a window is silent
_F0_LO_HZ = 50  # fundamental search band for harmonic periodicity
_F0_HI_HZ = 500


@dataclass(frozen=True)
class AudioWindowFlags:
    """Per-window event confidences in [0, 1]."""

    t: float
    speech_conf: float
    music_conf: float
    laughter_conf: float
    applause_conf: float


def spectral_flatness(mag: np.ndarray) -> float:
    """Wiener entropy in [0, 1]: ~1 for white-noise-like, ~0 for a pure tone."""
    if len(mag) == 0:
        return 0.0
    mag = np.maximum(mag, EPS)
    return float(np.exp(np.mean(np.log(mag))) / np.mean(mag))


def zero_crossing_rate(x: np.ndarray) -> float:
    """Fraction of adjacent samples that change sign (noisy/fricative → high)."""
    if len(x) < 2:
        return 0.0
    return float(np.mean(np.abs(np.diff(np.sign(x)))) / 2.0)


def harmonic_ratio(x: np.ndarray, sr: int) -> float:
    """Normalised autocorrelation peak in the F0 band (FFT-based, O(n log n))."""
    n = len(x)
    if n == 0:
        return 0.0
    spec = np.fft.rfft(x * np.hanning(n))
    ac = np.fft.irfft(spec * np.conj(spec), n=n)
    if ac[0] <= EPS:
        return 0.0
    ac = ac / ac[0]
    lo = max(1, sr // _F0_HI_HZ)
    hi = min(n - 1, sr // _F0_LO_HZ)
    if hi <= lo:
        return 0.0
    return float(np.clip(np.max(ac[lo:hi]), 0.0, 1.0))


def classify_window(t: float, zcr: float, flatness: float, harmonic_r: float) -> AudioWindowFlags:
    """Map window features to coarse event confidences (pure arithmetic, no branches)."""
    voiced = max(0.0, 1.0 - flatness)  # tonal energy share
    music_conf = round(voiced * harmonic_r, 4)
    applause_conf = round(flatness * min(1.0, zcr * 4.0), 4)
    laughter_conf = round(voiced * harmonic_r * min(1.0, zcr * 3.0), 4)
    speech_conf = round(voiced * (1.0 - harmonic_r) * min(1.0, zcr * 5.0), 4)
    return AudioWindowFlags(
        t=t,
        speech_conf=speech_conf,
        music_conf=music_conf,
        laughter_conf=laughter_conf,
        applause_conf=applause_conf,
    )


class AudioTagger(Protocol):
    """Stage 0 tagger seam: PCM bytes → per-window event flags (Phase-3 swap point)."""

    def tag(self, pcm: bytes, sr: int) -> tuple[AudioWindowFlags, ...]: ...


class HeuristicAudioTagger:
    """Default Stage 0 tagger — pure numpy over fixed 1 s windows."""

    def tag(self, pcm: bytes, sr: int = SR) -> tuple[AudioWindowFlags, ...]:
        x = decode_pcm(pcm, sr)
        win = int(sr * FLAG_WIN_S)
        n = len(x) // win
        flags: list[AudioWindowFlags] = []
        for i in range(n):
            seg = x[i * win : (i + 1) * win]
            t = i * FLAG_WIN_S
            rms = float(np.sqrt(np.mean(seg * seg)))
            if rms < SILENCE_RMS:
                flags.append(AudioWindowFlags(t, 0.0, 0.0, 0.0, 0.0))
                continue
            mag = np.abs(np.fft.rfft(seg))
            flags.append(
                classify_window(
                    t,
                    zero_crossing_rate(seg),
                    spectral_flatness(mag),
                    harmonic_ratio(seg, sr),
                )
            )
        return tuple(flags)


def extract_audio_flags(
    pcm: bytes, sr: int = SR, *, tagger: AudioTagger | None = None
) -> tuple[AudioWindowFlags, ...]:
    """Classify ``pcm`` into per-window event flags. ``tagger`` is the Phase-3 swap seam."""
    return (tagger or HeuristicAudioTagger()).tag(pcm, sr)
