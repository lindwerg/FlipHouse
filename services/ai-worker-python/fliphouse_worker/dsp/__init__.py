"""Stage 0 DSP (P2-S5) — local virality signals from ffmpeg + numpy, no LLM/GPU.

Energy peaks & dramatic pauses (audio_energy), scene cuts (scene_cuts), and
coarse laughter/music/applause/speech flags (audio_flags), bundled by
``extract_local_signals`` into an immutable ``LocalSignals`` that Stage A recall
consumes to snap clip boundaries and pre-rank candidates.
"""

from .audio_energy import AudioEnergy, Pause, extract_audio_energy
from .audio_flags import AudioWindowFlags, HeuristicAudioTagger, extract_audio_flags
from .local_signals import LocalSignals, extract_local_signals
from .scene_cuts import SceneCut, extract_scene_cuts

__all__ = [
    "AudioEnergy",
    "AudioWindowFlags",
    "HeuristicAudioTagger",
    "LocalSignals",
    "Pause",
    "SceneCut",
    "extract_audio_energy",
    "extract_audio_flags",
    "extract_local_signals",
    "extract_scene_cuts",
]
