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
import time
from collections.abc import Callable

SIGNATURE_HEADER = "x-fliphouse-signature"
TIMESTAMP_HEADER = "x-fliphouse-timestamp"
SIGNATURE_PREFIX = "sha256="

# Replay window: reject a signed request whose timestamp is more than this many seconds
# from our clock (in EITHER direction — stale OR future-skewed). The worker stamps
# ``int(time.time())`` right before the POST, so a legitimate inline call lands well
# within 60 s; anything older is a replay/relay and a stale request maps to a 401 (the
# worker's fail-open then degrades to CPU rather than hard-failing the render).
MAX_TIMESTAMP_AGE_S = 60

# Injectable clock seam: defaults to the real wall clock, overridden in tests so the
# offline suite stays deterministic (never calls ``time.time()`` un-mockably).
Now = Callable[[], float]


def compute_signature(secret: str, timestamp: str, raw_body: bytes) -> str:
    """Return ``sha256=<hex>`` for ``${timestamp}.${rawBody}`` (bytes-exact)."""
    message = timestamp.encode("utf-8") + b"." + raw_body
    digest = hmac.new(secret.encode("utf-8"), message, hashlib.sha256).hexdigest()
    return f"{SIGNATURE_PREFIX}{digest}"


def is_timestamp_fresh(
    timestamp: str,
    *,
    now: Now = time.time,
    max_age_s: int = MAX_TIMESTAMP_AGE_S,
) -> bool:
    """True when ``timestamp`` (unix seconds string) is within ``max_age_s`` of ``now``.

    Rejects a blank/non-numeric timestamp (``False``, → 401) and any value skewed more
    than ``max_age_s`` in either direction. ``now`` is injected so tests pin the clock.
    """
    if not timestamp.strip():
        return False
    try:
        stamped = float(timestamp)
    except ValueError:
        return False
    return abs(now() - stamped) <= max_age_s


def verify_signature(
    secret: str,
    timestamp: str,
    raw_body: bytes,
    provided: str,
    *,
    now: Now = time.time,
    max_age_s: int = MAX_TIMESTAMP_AGE_S,
) -> bool:
    """Constant-time signature check PLUS a timestamp replay-window check.

    ``provided`` is the raw header value (``sha256=<hex>``). Returns ``False`` for a
    missing/blank header, a STALE/future-skewed timestamp, or a signature mismatch —
    rather than raising — so the caller maps every failure to a clean 401. The clock is
    injected (``now``) so the offline suite stays deterministic.
    """
    if not provided:
        return False
    if not is_timestamp_fresh(timestamp, now=now, max_age_s=max_age_s):
        return False
    expected = compute_signature(secret, timestamp, raw_body)
    return hmac.compare_digest(expected, provided)
