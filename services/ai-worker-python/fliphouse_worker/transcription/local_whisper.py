"""CPU fallback provider: faster-whisper (CTranslate2, int8, NO torch).

This is the always-available, genuinely-$0 path — the only provider that
physically runs offline (in the golden test) and the degraded last resort when
every GPU provider fails. Per doc 01 §3 and roadmap step 2.4 it runs ``base``/
``cpu``/``int8`` (``small``/``medium`` only on total GPU failure — never the
~1.5 GB ``large-v3-turbo``, which would block the Railway CPU worker).

faster-whisper is LAZY-imported inside ``_load_model`` so importing this module
never pulls the C++ runtime, and the heavy real-model branch stays out of the
coverage gate (``# pragma: no cover``). Tests inject a fake ``model`` to cover
the whole transcribe path deterministically; the real model runs only under
``@pytest.mark.live``.
"""

from __future__ import annotations

from typing import Any

from .normalize import normalize_segments
from .provider import Transcript

WHISPER_DEVICE = "cpu"
WHISPER_COMPUTE = "int8"  # int8 quantization — fits the GPU-less Railway worker
DEFAULT_MODEL_SIZE = "base"  # doc 01 §3 baseline; founder may bump base→small at CHECKPOINT B


class LocalWhisperProvider:
    """faster-whisper CPU provider satisfying :class:`TranscriptionProvider`."""

    def __init__(
        self,
        model_size: str = DEFAULT_MODEL_SIZE,
        language: str = "ru",
        *,
        model: Any | None = None,
    ) -> None:
        self._model_size = model_size
        self._language = language
        self._model = model  # injected fake in tests; real model lazy-loaded otherwise

    def _load_model(self) -> Any:  # pragma: no cover - heavy real faster-whisper, live-only
        from faster_whisper import WhisperModel

        return WhisperModel(self._model_size, device=WHISPER_DEVICE, compute_type=WHISPER_COMPUTE)

    def transcribe(self, audio_ref: str, *, language: str | None = None) -> Transcript:
        lang = language or self._language
        model = self._model or self._load_model()
        segments, info = model.transcribe(
            audio_ref, language=lang, word_timestamps=True, vad_filter=True
        )

        raw_segments = [
            {
                "start": seg.start,
                "end": seg.end,
                "words": [
                    {"word": w.word, "start": w.start, "end": w.end} for w in (seg.words or ())
                ],
            }
            for seg in segments
        ]
        return normalize_segments(
            raw_segments,
            duration=float(getattr(info, "duration", 0.0)),
            language=lang,
            engine=f"faster-whisper-{self._model_size}",
        )
