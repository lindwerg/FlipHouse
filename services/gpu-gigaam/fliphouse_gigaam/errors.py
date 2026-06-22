"""Named errors for the GigaAM-v3 GPU transcription service.

Every failure path raises one of these so callers (and the orchestrator's
failure branch) can discriminate by type rather than by message string.
"""

from __future__ import annotations


class GigaamError(Exception):
    """Base class for every error this service raises."""


class InvalidSubmitRequest(GigaamError):
    """The ``/transcribe`` body is missing a field or carries a bad value."""


class AudioFetchError(GigaamError):
    """Fetching the ``audio_url`` failed (network, 4xx/5xx, or empty body)."""


class TranscriptionError(GigaamError):
    """The model seam (``transcribe_audio``) failed to produce a payload."""


class CallbackPostError(GigaamError):
    """The webhook POST to the receiver failed (transport or non-2xx)."""
