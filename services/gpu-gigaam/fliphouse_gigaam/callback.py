"""``sign_and_post`` — build the callback body, sign it, POST it to the receiver.

The body serialization + HMAC framing + header assembly is REAL and unit-tested:
a test recomputes the signature independently (exactly as the receiver does) and
asserts a match. Only the network POST is behind the injected ``HttpPoster`` seam,
whose real (httpx) implementation is ``# pragma: no cover``.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Protocol

from .contracts import (
    ENGINE_GIGAAM_V3,
    STATUS_FAILED,
    STATUS_SUCCEEDED,
    RawPayload,
)
from .errors import CallbackPostError
from .signing import sign_request

# A 2xx from the receiver means accepted; anything else is a delivery failure.
_HTTP_OK_MIN = 200
_HTTP_OK_MAX = 300


class PostResponse(Protocol):
    """The minimal response surface ``sign_and_post`` inspects."""

    status_code: int


# Injected network seam: (url, body_bytes, headers) -> response with status_code.
HttpPoster = Callable[[str, bytes, dict[str, str]], PostResponse]


def _serialize(body: dict) -> bytes:
    """Serialize to the EXACT bytes we sign and send.

    ``separators`` pins compact framing and ``ensure_ascii=False`` keeps Cyrillic
    as UTF-8; the resulting bytes are what both the signature and the wire use, so
    there is exactly one serialization.
    """
    return json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")


def build_success_body(request_id: str, payload: RawPayload) -> dict:
    """The success callback body: ``{request_id, status, engine, payload}``."""
    return {
        "request_id": request_id,
        "status": STATUS_SUCCEEDED,
        "engine": ENGINE_GIGAAM_V3,
        "payload": payload.to_dict(),
    }


def build_failure_body(request_id: str, error: str) -> dict:
    """The failure callback body: ``{request_id, status, error}``."""
    return {
        "request_id": request_id,
        "status": STATUS_FAILED,
        "error": error,
    }


def sign_and_post(
    *,
    poster: HttpPoster,
    secret: str,
    webhook_url: str,
    body: dict,
    timestamp: str,
) -> None:
    """Serialize → sign over ``${timestamp}.${rawBody}`` → POST the verbatim bytes.

    Raises :class:`CallbackPostError` on a non-2xx response or a transport fault
    surfaced by ``poster``; the caller (orchestrator) decides retry/abandon.
    """
    raw_body = _serialize(body)
    signed = sign_request(secret, timestamp, raw_body)
    try:
        response = poster(webhook_url, signed.body, signed.headers)
    except Exception as exc:  # noqa: BLE001 - normalize transport faults to our type
        raise CallbackPostError(f"callback POST transport error: {exc}") from exc
    if not (_HTTP_OK_MIN <= response.status_code < _HTTP_OK_MAX):
        raise CallbackPostError(f"callback POST rejected: status {response.status_code}")
