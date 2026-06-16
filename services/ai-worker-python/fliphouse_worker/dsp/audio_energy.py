"""Stage 0 audio DSP (P2-S5): RMS energy envelope, peaks, and dramatic pauses.

The source audio is decoded ONCE to mono 16 kHz PCM via a single ffmpeg pipe
(``_run_audio_ffmpeg`` — the only impure boundary, mocked in tests by patching
``subprocess.run``). Everything downstream is pure numpy: an energy envelope,
loud-burst peaks (laughter/shout/beat-drop), and low-energy runs (dramatic
pauses) used by Stage A to snap clip boundaries.

ffmpeg is used purely as a decoder (``-map a:0 -vn``), so the LGPL/no-x264
Railway build is unaffected — no video codec is touched. The envelope is a
sharper transient localiser than ebur128 (whose 400 ms integrator smears the
very spikes we want), which is why we decode raw PCM instead of parsing astats.
"""

from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import NamedTuple

import numpy as np

SR = 16000  # decode sample rate (Hz); plenty for an energy envelope, quarters bytes vs 48k
HOP = 1600  # window length in samples = 100 ms at 16 kHz
EPS = 1e-10  # log/zero-division floor
SILENCE_DBFS = -45.0  # below this a window counts as "quiet"
MIN_PAUSE_S = 0.4  # a quiet run shorter than this is not a dramatic pause
PEAK_Z_THRESH = 3.0  # robust z-score above which a window is an energy peak


@dataclass(frozen=True)
class Pause:
    """A contiguous low-energy span (dramatic pause), seconds."""

    start: float
    end: float

    @property
    def mid(self) -> float:
        return (self.start + self.end) / 2.0


class EnvelopeResult(NamedTuple):
    t: np.ndarray  # window start times (s)
    rms: np.ndarray  # linear RMS per window
    dbfs: np.ndarray  # dBFS per window


class AudioEnergy(NamedTuple):
    peaks_s: tuple[float, ...]  # window times of loud bursts
    pauses: tuple[Pause, ...]  # dramatic pauses


def _run_audio_ffmpeg(src: str) -> bytes:
    """Decode ``src`` to mono 16 kHz s16le PCM on stdout (the only ffmpeg call)."""
    return subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostdin",
            "-loglevel",
            "error",
            "-i",
            src,
            "-map",
            "a:0",
            "-ac",
            "1",
            "-ar",
            str(SR),
            "-vn",
            "-f",
            "s16le",
            "-acodec",
            "pcm_s16le",
            "pipe:1",
        ],
        check=True,
        capture_output=True,
    ).stdout


def decode_pcm(raw: bytes, sr: int = SR) -> np.ndarray:
    """s16le bytes → float32 samples in [-1, 1]. Odd trailing byte is dropped."""
    even = raw[: len(raw) - (len(raw) % 2)]
    return np.frombuffer(even, dtype="<i2").astype(np.float32) / 32768.0


def energy_envelope(x: np.ndarray, hop: int = HOP, sr: int = SR) -> EnvelopeResult:
    """Per-window RMS / dBFS envelope. Empty arrays when the signal is shorter than a hop."""
    n = len(x) // hop
    if n == 0:
        empty = np.zeros(0, dtype=np.float32)
        return EnvelopeResult(empty, empty, empty)
    frames = x[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames * frames, axis=1))
    dbfs = 20.0 * np.log10(np.maximum(rms, EPS))
    t = np.arange(n) * (hop / sr)
    return EnvelopeResult(t, rms, dbfs)


def detect_energy_peaks(
    t: np.ndarray, dbfs: np.ndarray, z_thresh: float = PEAK_Z_THRESH
) -> tuple[float, ...]:
    """Windows whose dBFS is a robust-z outlier above the median (loud bursts)."""
    if len(dbfs) == 0:
        return ()
    med = float(np.median(dbfs))
    mad = float(np.median(np.abs(dbfs - med))) + EPS
    z = 0.6745 * (dbfs - med) / mad
    return tuple(float(t[i]) for i in np.flatnonzero(z > z_thresh))


def detect_pauses(
    t: np.ndarray, dbfs: np.ndarray, hop: int = HOP, sr: int = SR
) -> tuple[Pause, ...]:
    """Contiguous dBFS < SILENCE_DBFS runs lasting at least MIN_PAUSE_S."""
    if len(dbfs) == 0:
        return ()
    quiet = (dbfs < SILENCE_DBFS).astype(np.int8)
    edges = np.diff(np.concatenate(([0], quiet, [0])))
    starts = np.flatnonzero(edges == 1)
    ends = np.flatnonzero(edges == -1)
    win = hop / sr
    pauses: list[Pause] = []
    for s, e in zip(starts, ends, strict=False):
        if (e - s) * win >= MIN_PAUSE_S:
            pauses.append(Pause(start=float(t[s]), end=float(t[e - 1] + win)))
    return tuple(pauses)


def audio_energy_from_pcm(raw: bytes) -> AudioEnergy:
    """Pure path: PCM bytes → energy peaks + pauses (no ffmpeg)."""
    env = energy_envelope(decode_pcm(raw))
    return AudioEnergy(
        peaks_s=detect_energy_peaks(env.t, env.dbfs),
        pauses=detect_pauses(env.t, env.dbfs),
    )


def extract_audio_energy(
    src: str, *, _run_fn: Callable[[str], bytes] = _run_audio_ffmpeg
) -> AudioEnergy:
    """Decode ``src`` and extract energy peaks + pauses. ``_run_fn`` is the test seam."""
    return audio_energy_from_pcm(_run_fn(src))
