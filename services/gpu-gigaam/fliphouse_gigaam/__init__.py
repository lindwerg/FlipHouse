"""FlipHouse GigaAM-v3 GPU transcription service (P2 step #1, TRACK D).

A production-correct SKELETON: the ASGI app, the wire contracts, REAL HMAC
signing, and the full fetch→transcribe→sign-and-post orchestration with every
impure boundary injected. The HEAVY ML (GigaAM weights, pyannote VAD, GPU, the
Docker image, deploy) is FOUNDER-GATED — see README.md. The injected seams whose
real bodies need a GPU or live network are ``# pragma: no cover``; the
marshalling/HMAC/orchestration logic around them is 100% unit-covered.
"""

from __future__ import annotations

from .align import (
    ENV_FORCED_ALIGN,
    CtcAlignFn,
    forced_align_enabled,
    realign_payload,
    resolve_align_fn,
)
from .app import AppDeps, create_app
from .contracts import RawPayload, Segment, SubmitRequest, Word
from .orchestrator import TranscribeDeps, run_transcription
from .signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, compute_signature

__all__ = [
    "AppDeps",
    "CtcAlignFn",
    "ENV_FORCED_ALIGN",
    "RawPayload",
    "SIGNATURE_HEADER",
    "Segment",
    "SubmitRequest",
    "TIMESTAMP_HEADER",
    "TranscribeDeps",
    "Word",
    "compute_signature",
    "create_app",
    "forced_align_enabled",
    "realign_payload",
    "resolve_align_fn",
    "run_transcription",
]
