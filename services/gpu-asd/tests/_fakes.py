"""Shared ASGI-driving helpers for the app tests (no live socket)."""

from __future__ import annotations

import asyncio
import json

from fliphouse_asd.signing import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
)


def drive(app, method: str, path: str, *, body: bytes = b"", headers=None) -> tuple[int, dict]:
    """Run one request through an ASGI ``app`` and return ``(status, json_body)``."""
    sent: list[dict] = []
    request_headers = list(headers or [])

    async def run() -> None:
        scope = {"type": "http", "method": method, "path": path, "headers": request_headers}
        events = iter([{"type": "http.request", "body": body, "more_body": False}])

        async def receive() -> dict:
            return next(events)

        async def send(message: dict) -> None:
            sent.append(message)

        await app(scope, receive, send)

    asyncio.run(run())
    status = next(m["status"] for m in sent if m["type"] == "http.response.start")
    raw = next(m["body"] for m in sent if m["type"] == "http.response.body")
    return status, json.loads(raw)


def signed_headers(secret: str, timestamp: str, body: bytes) -> list[tuple[bytes, bytes]]:
    """Build the ``x-fliphouse-*`` header pair the service verifies."""
    sig = compute_signature(secret, timestamp, body)
    return [
        (TIMESTAMP_HEADER.encode("latin-1"), timestamp.encode("latin-1")),
        (SIGNATURE_HEADER.encode("latin-1"), sig.encode("latin-1")),
    ]
