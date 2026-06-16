"""Stage 0 facade (P2-S5): one call → all local DSP signals.

Decodes the source audio ONCE and derives both the energy signals and the event
flags from the same PCM (one ffmpeg audio pass), runs scene detection in a
second video pass, and bundles everything into an immutable ``LocalSignals``.
The two ffmpeg calls are injected (``_run_audio_fn`` / ``_run_video_fn``) so the
whole module is unit-testable with zero ffmpeg.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from .audio_energy import Pause, audio_energy_from_pcm
from .audio_energy import _run_audio_ffmpeg as _default_audio_fn
from .audio_flags import AudioWindowFlags, extract_audio_flags
from .scene_cuts import SceneCut, parse_cuts
from .scene_cuts import _run_video_ffmpeg as _default_video_fn


@dataclass(frozen=True)
class LocalSignals:
    """All Stage 0 signals for one source video."""

    pauses: tuple[Pause, ...]
    energy_peaks_s: tuple[float, ...]
    scene_cuts: tuple[SceneCut, ...]
    audio_flags: tuple[AudioWindowFlags, ...]


def extract_local_signals(
    src: str,
    *,
    _run_audio_fn: Callable[[str], bytes] = _default_audio_fn,
    _run_video_fn: Callable[[str], str] = _default_video_fn,
) -> LocalSignals:
    """Extract energy peaks, dramatic pauses, scene cuts, and event flags from ``src``."""
    raw = _run_audio_fn(src)
    energy = audio_energy_from_pcm(raw)
    return LocalSignals(
        pauses=energy.pauses,
        energy_peaks_s=energy.peaks_s,
        scene_cuts=parse_cuts(_run_video_fn(src)),
        audio_flags=extract_audio_flags(raw),
    )
