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
# Energy peaks are LOCAL events (a laugh/shout/beat-drop louder than its surroundings),
# not global outliers — a global robust-z misses them on long video where overall
# loudness varies. So a peak is the max of a short neighborhood AND clears the local
# median by a margin.
PEAK_LOCAL_WIN_S = 2.0  # neighborhood width for the local baseline (s)
PEAK_MARGIN_DB = 6.0  # a peak must exceed its local-median baseline by this many dB
MIN_PEAK_DIST_S = 1.0  # collapse peaks closer than this together (keep the first)


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
    t: np.ndarray, dbfs: np.ndarray, hop: int = HOP, sr: int = SR
) -> tuple[float, ...]:
    """Local loud bursts: a window that is the max of its ~2 s neighborhood AND
    exceeds the neighborhood's median by PEAK_MARGIN_DB. Peaks closer than
    MIN_PEAK_DIST_S are collapsed (the first is kept)."""
    n = len(dbfs)
    if n == 0:
        return ()
    half = max(1, round(PEAK_LOCAL_WIN_S / (hop / sr) / 2))
    window = 2 * half + 1
    padded = np.pad(dbfs, half, mode="edge")
    neighborhoods = np.lib.stride_tricks.sliding_window_view(padded, window)
    local_max = neighborhoods.max(axis=1)
    local_median = np.median(neighborhoods, axis=1)
    is_peak = (dbfs >= local_max - EPS) & (dbfs - local_median >= PEAK_MARGIN_DB)

    min_gap = max(1, round(MIN_PEAK_DIST_S / (hop / sr)))
    peaks: list[float] = []
    last = -min_gap
    for i in np.flatnonzero(is_peak):
        if i - last >= min_gap:
            peaks.append(float(t[i]))
            last = int(i)
    return tuple(peaks)


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
