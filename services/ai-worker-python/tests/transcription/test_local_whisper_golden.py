"""LocalWhisperProvider — deterministic via an injected fake model; live-gated real run.

CI covers the whole transcribe path with a FAKE WhisperModel (no faster-whisper
install, no torch, no audio decode). The genuine faster-whisper run is opt-in
(`FLIPHOUSE_LIVE_WHISPER`) + `# pragma: no cover`, mirroring the live-Gemini
pattern — it never runs in the coverage gate.
"""

from __future__ import annotations

import os
from collections.abc import Callable
from pathlib import Path

import pytest

from fliphouse_worker.transcription import LocalWhisperProvider
from fliphouse_worker.transcription.local_whisper import WHISPER_COMPUTE, WHISPER_DEVICE


class _FakeWord:
    def __init__(self, word, start, end):
        self.word = word
        self.start = start
        self.end = end


class _FakeSegment:
    def __init__(self, start, end, words):
        self.start = start
        self.end = end
        self.words = words


class _FakeInfo:
    duration = 2.0


class _FakeModel:
    """Mimics faster-whisper: ``transcribe`` → (segments_iterable, info)."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio_ref, **kwargs):
        self.calls.append((audio_ref, kwargs))
        segments = [
            _FakeSegment(0.0, 1.0, [_FakeWord(" Привет", 0.0, 0.5), _FakeWord(" мир", 0.5, 1.0)]),
            _FakeSegment(1.0, 2.0, None),  # a segment with no words → `seg.words or ()` path
        ]
        return iter(segments), _FakeInfo()


def test_local_whisper_transcribe_offline_with_fake_model():
    model = _FakeModel()
    provider = LocalWhisperProvider(model_size="base", model=model)
    t = provider.transcribe("clip.mp4")

    # word_timestamps + vad_filter + language are requested of faster-whisper.
    _, kwargs = model.calls[0]
    assert kwargs["word_timestamps"] is True
    assert kwargs["vad_filter"] is True
    assert kwargs["language"] == "ru"

    assert t.engine == "faster-whisper-base"
    assert t.duration == 2.0
    assert [w.word for w in t.word_segments[0].words] == [" Привет", " мир"]
    assert t.word_segments[1].words == ()  # None words normalized to empty
    assert t.segments[0].text == "Привет мир"


def test_local_whisper_language_override():
    model = _FakeModel()
    LocalWhisperProvider(model=model).transcribe("clip.mp4", language="en")
    assert model.calls[0][1]["language"] == "en"


def test_local_whisper_uses_cpu_int8_constants():
    # doc 01 §3 / roadmap 2.4: device=cpu, compute_type=int8 (the GPU-less baseline).
    assert WHISPER_DEVICE == "cpu"
    assert WHISPER_COMPUTE == "int8"


@pytest.mark.skipif(
    not os.getenv("FLIPHOUSE_LIVE_WHISPER"),
    reason="live test — set FLIPHOUSE_LIVE_WHISPER=1 and `pip install -e .[transcription]`",
)
@pytest.mark.live
def test_live_local_whisper_runs_on_golden_fixture(
    make_test_clip: Callable[[], Path],
):  # pragma: no cover
    # Real faster-whisper on the deterministic ffmpeg fixture — proves the offline
    # CPU path end-to-end (the 1s sine clip yields a valid, possibly-empty transcript).
    clip = make_test_clip()
    t = LocalWhisperProvider(model_size="base").transcribe(str(clip))
    assert t.engine == "faster-whisper-base"
    assert t.duration >= 0.0
    for entry in t.to_word_segments():
        for w in entry["words"]:
            assert w["word"].startswith(" ")
