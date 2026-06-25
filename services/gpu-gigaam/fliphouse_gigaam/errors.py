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


# Stable, machine-greppable prefix for an HF/pyannote auth-class transcription
# fault (a gated-VAD rejection / expired or terms-unaccepted HF_TOKEN). The webhook
# receiver keys off this prefix to surface a DISTINCT, operator-actionable fail
# reason instead of a generic "failed" (TRANS-4) — an expired token then reads as
# itself in the asr-fail error rather than masquerading as a transcription fault.
GIGAAM_AUTH_ERROR_PREFIX = "gigaam-auth-error:"

# Substrings (lowercased) that mark an HF/pyannote authentication / gated-access
# failure. pyannote raises a generic exception on a gated-model rejection, so we
# match on its message rather than a type — kept conservative to avoid relabeling a
# genuine transcription fault as auth.
_AUTH_ERROR_MARKERS = (
    "hf_token",
    "huggingface",
    "401",
    "403",
    "unauthorized",
    "access to model",
    "gated",
    "accept the terms",
    "use_auth_token",
    "is not authorized",
)


def is_hf_auth_error(exc: BaseException) -> bool:
    """True when ``exc`` looks like an HF/pyannote gated-VAD auth failure.

    Matches conservatively on the message text (lowercased) so only a clear
    auth/gated-access signal is reclassified; any other fault stays a normal
    transcription error.
    """
    message = str(exc).lower()
    return any(marker in message for marker in _AUTH_ERROR_MARKERS)


def classify_transcription_error(exc: BaseException) -> str:
    """Build the error string for a transcription fault.

    An HF/pyannote auth failure is tagged with :data:`GIGAAM_AUTH_ERROR_PREFIX` so
    the receiver can surface it as a distinct, diagnosable fail reason; any other
    fault returns its plain message.
    """
    if is_hf_auth_error(exc):
        return f"{GIGAAM_AUTH_ERROR_PREFIX} {exc}"
    return str(exc)
