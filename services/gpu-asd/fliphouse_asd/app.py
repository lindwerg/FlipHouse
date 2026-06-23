"""A framework-light ASGI app exposing ``POST /score`` and ``GET /health``.

No FastAPI/pydantic dependency — a minimal ASGI callable so the whole request path
is unit-testable by driving the coroutine with fake ``receive``/``send`` (no live
socket). Unlike the GigaAM submit-and-park lane, ``/score`` is SYNCHRONOUS: the
worker blocks on it inline during the render, so the model runs and the score grid
is returned in the SAME response (200). The flow is:

  1. read the body (size-capped),
  2. verify the HMAC signature over the EXACT raw bytes (→ 401 on mismatch),
  3. validate the JSON into a :class:`ScoreRequest` (→ 400 on bad shape),
  4. run the injected scoring seam and return ``200 {engine, scores}`` (→ 500 on a
     model fault, which the worker treats as "fail open to CPU").
"""

from __future__ import annotations

import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field

from .errors import InvalidScoreRequest, ScoringError
from .scoring import ScoreFn, run_scoring
from .signing import SIGNATURE_HEADER, TIMESTAMP_HEADER, Now, verify_signature
from .validate import parse_score_request

_SCORE_PATH = "/score"
_HEALTH_PATH = "/health"
_MAX_BODY_BYTES = 4_194_304  # 4 MiB — face-box grids are small, but cap defensively.


@dataclass(frozen=True)
class AppDeps:
    """The app's injected boundaries: the HMAC secret + the LR-ASD scoring seam + clock.

    ``now`` is the injectable wall clock used by the signature replay-window check; it
    defaults to ``time.time`` in production and is pinned by the unit suite so signed
    requests with a fixed timestamp verify deterministically (no real clock dependency).
    """

    secret: str
    score_fn: ScoreFn
    now: Now = field(default=time.time)


async def _read_body(receive: Callable[[], Awaitable[dict]]) -> bytes:
    """Drain the ASGI request-body events (with a size ceiling)."""
    chunks: list[bytes] = []
    total = 0
    more = True
    while more:
        event = await receive()
        body = event.get("body", b"")
        total += len(body)
        if total > _MAX_BODY_BYTES:
            raise InvalidScoreRequest("request body too large")
        chunks.append(body)
        more = event.get("more_body", False)
    return b"".join(chunks)


async def _send_json(send: Callable[[dict], Awaitable[None]], status: int, body: dict) -> None:
    """Emit an ASGI JSON response (start + body)."""
    raw = json.dumps(body, ensure_ascii=False).encode("utf-8")
    await send(
        {
            "type": "http.response.start",
            "status": status,
            "headers": [(b"content-type", b"application/json")],
        }
    )
    await send({"type": "http.response.body", "body": raw})


def _header(scope: dict, name: str) -> str:
    """Read a (lower-cased) request header value from the ASGI scope, or ``""``."""
    target = name.encode("latin-1")
    for key, value in scope.get("headers", ()):
        if key == target:
            return value.decode("latin-1")
    return ""


async def _handle_score(
    deps: AppDeps,
    scope: dict,
    receive: Callable[[], Awaitable[dict]],
    send: Callable[[dict], Awaitable[None]],
) -> None:
    try:
        raw = await _read_body(receive)
    except InvalidScoreRequest as exc:
        await _send_json(send, 400, {"error": str(exc)})
        return

    timestamp = _header(scope, TIMESTAMP_HEADER)
    signature = _header(scope, SIGNATURE_HEADER)
    # Verify HMAC + the timestamp replay window (stale → 401, so the worker fails OPEN
    # to CPU rather than hard-failing the render). The clock is injected via deps.now.
    if not verify_signature(deps.secret, timestamp, raw, signature, now=deps.now):
        await _send_json(send, 401, {"error": "invalid signature"})
        return

    try:
        decoded = json.loads(raw)
        req = parse_score_request(decoded)
    except (InvalidScoreRequest, json.JSONDecodeError) as exc:
        await _send_json(send, 400, {"error": str(exc)})
        return

    try:
        response = run_scoring(req, deps.score_fn)
    except ScoringError as exc:
        await _send_json(send, 500, {"error": str(exc)})
        return
    await _send_json(send, 200, response.to_dict())


def create_app(deps: AppDeps) -> Callable:
    """Build the ASGI application closure over the injected ``deps``."""

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":  # pragma: no cover - lifespan/ws not served
            return
        method = scope["method"]
        path = scope["path"]
        if method == "POST" and path == _SCORE_PATH:
            await _handle_score(deps, scope, receive, send)
        elif method == "GET" and path == _HEALTH_PATH:
            await _send_json(send, 200, {"status": "ok"})
        else:
            await _send_json(send, 404, {"error": "not found"})

    return app
