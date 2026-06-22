"""Transcription stage (P2-S2.4): provider-abstracted, free-first.

Public surface:

* :class:`TranscriptionProvider` / :class:`Transcript` (+ ``Segment``, ``WordSegment``,
  ``Word``) — the contract.
* :class:`LocalWhisperProvider` — the genuinely-$0 CPU fallback (faster-whisper).
* :class:`CloudTranscriptionProvider` — the GigaAM-v3 primary behind an injected
  transport (real webhook wiring + live RU validation land in a later step).
* :class:`FallbackTranscriber` — primary→fallback resilience (logged, never silent).
* :func:`select_provider` — the single swap point (mirrors ``llm/routes.py``).
"""

from __future__ import annotations

import logging
from typing import Any

from .cloud import CloudTranscriptionProvider, Transport
from .local_whisper import LocalWhisperProvider
from .normalize import leading_space, normalize_segments
from .provider import (
    Segment,
    Transcript,
    TranscriptionProvider,
    Word,
    WordSegment,
)
from .raw_payload import GigaamPayloadError, ValidatedPayload, validate_gigaam_payload

logger = logging.getLogger(__name__)

__all__ = [
    "CloudTranscriptionProvider",
    "FallbackTranscriber",
    "GigaamPayloadError",
    "LocalWhisperProvider",
    "Segment",
    "Transcript",
    "TranscriptionProvider",
    "Transport",
    "ValidatedPayload",
    "Word",
    "WordSegment",
    "leading_space",
    "normalize_segments",
    "select_provider",
    "validate_gigaam_payload",
]


class FallbackTranscriber:
    """Try the primary; on ANY failure, log it with context and use the fallback.

    The fallback is a deliberate resilience path, not a swallowed error: the
    primary's exception is logged (``logger.warning`` with the engine + ref) so a
    silent degradation never goes unnoticed in production logs.
    """

    def __init__(self, primary: TranscriptionProvider, fallback: TranscriptionProvider) -> None:
        self._primary = primary
        self._fallback = fallback

    def transcribe(self, audio_ref: str, *, language: str | None = None) -> Transcript:
        try:
            return self._primary.transcribe(audio_ref, language=language)
        except Exception as exc:
            logger.warning(
                "transcription primary failed for %s (%s); using fallback",
                audio_ref,
                exc,
                exc_info=True,  # keep the traceback for Railway-log triage
            )
            return self._fallback.transcribe(audio_ref, language=language)


def select_provider(
    prefer: str = "cloud",
    *,
    transport: Transport | None = None,
    local_model: Any | None = None,
    language: str = "ru",
) -> TranscriptionProvider:
    """Return a provider: cloud primary with local fallback, else local only.

    With a ``transport`` and ``prefer='cloud'`` (the default), the cloud GigaAM-v3
    primary is wrapped in a :class:`FallbackTranscriber` over the CPU provider, so
    a primary outage degrades to the free local path instead of failing the job.

    The ONLY way to get the CPU provider is the EXPLICIT ``prefer='local'`` path.
    Requesting ``prefer='cloud'`` (the default) WITHOUT a transport is a wiring
    bug: it used to silently return LocalWhisper, so the GigaAM-v3 primary never
    ran in production and every job quietly degraded to faster-whisper CPU. That
    silent degradation is now a loud failure.
    """
    local = LocalWhisperProvider(language=language, model=local_model)
    if prefer == "local":
        return local
    if transport is None:
        raise ValueError(
            "cloud transcription requested but no transport provided — "
            "refusing silent LocalWhisper fallback"
        )
    cloud = CloudTranscriptionProvider(transport=transport, language=language)
    return FallbackTranscriber(cloud, local)
