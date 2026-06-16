"""select_provider factory + FallbackTranscriber primary→fallback resilience."""

from __future__ import annotations

import logging

from fliphouse_worker.transcription import (
    CloudTranscriptionProvider,
    FallbackTranscriber,
    LocalWhisperProvider,
    normalize_segments,
    select_provider,
)

_LOCAL_RAW = [{"start": 0.0, "end": 1.0, "words": [{"word": "x", "start": 0.0, "end": 1.0}]}]


def _local_transcript():
    return normalize_segments(_LOCAL_RAW, duration=1.0, language="ru", engine="faster-whisper-base")


class _BoomProvider:
    def transcribe(self, audio_ref, *, language="ru"):
        raise RuntimeError("primary down")


class _OkProvider:
    def __init__(self, tag):
        self._tag = tag

    def transcribe(self, audio_ref, *, language="ru"):
        return normalize_segments(_LOCAL_RAW, duration=1.0, language=language, engine=self._tag)


def test_select_provider_without_transport_returns_local():
    p = select_provider(transport=None)
    assert isinstance(p, LocalWhisperProvider)


def test_select_provider_prefer_local_ignores_transport():
    p = select_provider("local", transport=lambda ref, lang: {"segments": [], "duration": 0.0})
    assert isinstance(p, LocalWhisperProvider)


def test_select_provider_with_transport_wraps_cloud_with_fallback():
    p = select_provider(transport=lambda ref, lang: {"segments": [], "duration": 0.0})
    assert isinstance(p, FallbackTranscriber)
    assert isinstance(p._primary, CloudTranscriptionProvider)
    assert isinstance(p._fallback, LocalWhisperProvider)


def test_fallback_returns_primary_on_success():
    fb = FallbackTranscriber(_OkProvider("gigaam-v3"), _OkProvider("faster-whisper-base"))
    assert fb.transcribe("a").engine == "gigaam-v3"


def test_fallback_uses_local_and_logs_on_primary_failure(caplog):
    fb = FallbackTranscriber(_BoomProvider(), _OkProvider("faster-whisper-base"))
    with caplog.at_level(logging.WARNING):
        result = fb.transcribe("r2://job/audio.wav")
    assert result.engine == "faster-whisper-base"
    assert "primary failed" in caplog.text
    assert "r2://job/audio.wav" in caplog.text


def test_select_provider_integration_local_path_produces_contract():
    # Full local path via injected fake model through the factory's local provider.
    class _Model:
        def transcribe(self, audio_ref, **kwargs):
            class _W:
                word, start, end = " слово", 0.0, 1.0

            class _S:
                start, end, words = 0.0, 1.0, [_W()]

            class _I:
                duration = 1.0

            return iter([_S()]), _I()

    p = select_provider("local", local_model=_Model())
    t = p.transcribe("clip.mp4")
    assert t.segments[0].text == "слово"
    assert _local_transcript().engine == "faster-whisper-base"
