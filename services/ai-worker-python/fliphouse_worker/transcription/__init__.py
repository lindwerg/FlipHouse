"""Transcription stage (P2-S2.4): provider-abstracted, GigaAM-v3 only.

GigaAM-v3 is the SOLE ASR engine. There is no CPU/whisper fallback anymore: the
live ASR path is the GPU submit-and-park lane (Node ``executeAsr`` → Modal
GigaAM → webhook → the ``asr-finalize`` CLI, which normalizes the raw payload
directly). When the GPU lane is unavailable, ASR must fail LOUD — never degrade
to a silent local text path.

Public surface:

* :class:`TranscriptionProvider` / :class:`Transcript` (+ ``Segment``, ``WordSegment``,
  ``Word``) — the contract.
* :class:`CloudTranscriptionProvider` — the GigaAM-v3 provider behind an injected
  transport.
* :func:`select_provider` — the single swap point (mirrors ``llm/routes.py``);
  cloud-only, raises when no transport is wired.
"""

from __future__ import annotations

from .cloud import CloudTranscriptionProvider, Transport
from .normalize import leading_space, normalize_segments
from .provider import (
    Segment,
    Transcript,
    TranscriptionProvider,
    Word,
    WordSegment,
)
from .raw_payload import GigaamPayloadError, ValidatedPayload, validate_gigaam_payload

__all__ = [
    "CloudTranscriptionProvider",
    "GigaamPayloadError",
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


def select_provider(
    *,
    transport: Transport | None = None,
    language: str = "ru",
) -> TranscriptionProvider:
    """Return the cloud GigaAM-v3 provider behind ``transport``.

    GigaAM-v3 is the sole engine, so there is no fallback wrap. A missing
    ``transport`` is a wiring bug, not a degradation path: it raises instead of
    silently producing text, since the only correct ASR path is the GPU lane.
    """
    if transport is None:
        raise ValueError(
            "cloud transcription requested but no transport provided — "
            "GigaAM-v3 is the sole engine; enable the GPU ASR lane (GPU_ASR_ENABLED=true)"
        )
    return CloudTranscriptionProvider(transport=transport, language=language)
