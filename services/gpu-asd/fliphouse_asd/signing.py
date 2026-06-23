"""HMAC-SHA256 request verification — the mirror of the worker's signer.

The worker (``services/ai-worker-python`` → ``speaker_region._live_asd_transport``)
signs each ``/score`` POST as ``hex(hmacSHA256(GPU_ASD_SECRET, `${timestamp}.${rawBody}`))``
and sends it in the ``x-fliphouse-signature`` header (``sha256=<hex>``) alongside
``x-fliphouse-timestamp``. This service recomputes the same framing over the EXACT
raw bytes it received and compares CONSTANT-TIME — the identical scheme the GigaAM
webhook-receiver uses, so the secret-management story is uniform across the fleet.
"""

from __future__ import annotations

import hashlib
import hmac

SIGNATURE_HEADER = "x-fliphouse-signature"
TIMESTAMP_HEADER = "x-fliphouse-timestamp"
SIGNATURE_PREFIX = "sha256="


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return ``sha256=<hex>`` for ``${timestamp}.${rawBody}`` (bytes-exact)."""
    message = timestamp.encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def verify_signature(secret: str, timestamp: str, raw_body: bytes, provided: str) -> bool:
    """Constant-time check that ``provided`` matches the recomputed signature.

    ``provided`` is the raw header value (``sha256=<hex>``). Returns ``False`` for a
    missing/blank header rather than raising, so the caller maps it to a clean 401.
    """
    if not provided:
        return False
    expected = compute_signature(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, provided)
