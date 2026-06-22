"""Real HMAC-SHA256 request signing — the exact framing the webhook-receiver
verifies.

The receiver (``apps/webhook-receiver``) recomputes
``hex(hmacSHA256(GIGAAM_WEBHOOK_SECRET, `${timestamp}.${rawBody}`))`` and compares
it (constant-time) against the ``sha256=<hex>`` value in the
``x-fliphouse-signature`` header. The signed message is the literal
``${timestamp}.${rawBody}`` over the EXACT raw bytes we POST — so the body must be
serialized once and both signed and sent verbatim.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass

# Header names — must match SIGNATURE_HEADER / TIMESTAMP_HEADER in the receiver.
SIGNATURE_HEADER = "x-fliphouse-signature"
TIMESTAMP_HEADER = "x-fliphouse-timestamp"

# The receiver expects the algorithm prefix on the signature value.
SIGNATURE_PREFIX = "sha256="


@dataclass(frozen=True)
class SignedRequest:
    """A body plus the two headers that authenticate it. ``body`` is the EXACT
    bytes that were signed and must be the EXACT bytes sent on the wire."""

    body: bytes
    headers: dict[str, str]


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return ``sha256=<hex>`` for ``${timestamp}.${rawBody}``.

    ``raw_body`` is bytes (the serialized JSON), ``timestamp`` is unix seconds as
    a string; the signed message is ``f"{timestamp}.".encode() + raw_body`` so the
    body bytes are never re-encoded or re-ordered.
    """
    message = timestamp.encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def sign_request(secret: str, timestamp: str, raw_body: bytes) -> SignedRequest:
    """Bundle ``raw_body`` with its signature + timestamp headers."""
    signature = compute_signature(secret, timestamp, raw_body)
    headers = {
        "content-type": "application/json",
        SIGNATURE_HEADER: signature,
        TIMESTAMP_HEADER: timestamp,
    }
    return SignedRequest(body=raw_body, headers=headers)
