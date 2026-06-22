"""A framework-light ASGI app exposing ``/transcribe`` and ``/status/<id>``.

No FastAPI/pydantic dependency — a minimal ASGI callable so the whole request
path is unit-testable by driving the coroutine with fake ``receive``/``send``
(no live socket). ``POST /transcribe`` validates the body, marks
``status=processing``, schedules :func:`run_transcription` via the injected
``schedule`` seam, and answers ``202 {request_id, status:"accepted"}`` WITHOUT
blocking on the work. ``GET /status/<id>`` reads the injected store.

The default ``schedule`` uses ``asyncio.create_task`` (real background task,
``# pragma: no cover``); the unit suite injects a synchronous scheduler that runs
the job inline so it can assert the posted callback + status transitions.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable
from dataclasses import dataclass

from .contracts import STATUS_ACCEPTED
from .errors import InvalidSubmitRequest
from .orchestrator import TranscribeDeps, run_transcription
from .validate import parse_submit_request

_TRANSCRIBE_PATH = "/transcribe"
_STATUS_PREFIX = "/status/"
_MAX_BODY_BYTES = 1_048_576

# Injected background-task seam: hand it the (no-arg) job to run off the response.
Schedule = Callable[[Callable[[], None]], None]


def _default_schedule(job: Callable[[], None]) -> None:  # pragma: no cover - event loop
    """Run ``job`` in a worker thread so the model call never blocks the loop."""
    asyncio.get_event_loop().run_in_executor(None, job)


@dataclass(frozen=True)
class AppDeps:
    """The app's injected boundaries: the job deps + the background scheduler."""

    transcribe: TranscribeDeps
    schedule: Schedule = _default_schedule


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
            raise InvalidSubmitRequest("request body too large")
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


async def _handle_transcribe(
    deps: AppDeps,
    receive: Callable[[], Awaitable[dict]],
    send: Callable[[dict], Awaitable[None]],
) -> None:
    try:
        raw = await _read_body(receive)
        decoded = json.loads(raw)
        req = parse_submit_request(decoded)
    except (InvalidSubmitRequest, json.JSONDecodeError) as exc:
        await _send_json(send, 400, {"error": str(exc)})
        return

    # Mark processing SYNCHRONOUSLY before scheduling so an immediate GET /status
    # is truthful, then answer 202 without awaiting the (background) work.
    deps.transcribe.store.mark_processing(req.request_id)
    deps.schedule(lambda: run_transcription(req, deps.transcribe))
    await _send_json(send, 202, {"request_id": req.request_id, "status": STATUS_ACCEPTED})


async def _handle_status(
    deps: AppDeps,
    path: str,
    send: Callable[[dict], Awaitable[None]],
) -> None:
    request_id = path[len(_STATUS_PREFIX) :]
    record = deps.transcribe.store.get(request_id)
    if record is None:
        await _send_json(send, 404, {"error": "unknown request_id"})
        return
    await _send_json(send, 200, record.to_dict())


def create_app(deps: AppDeps) -> Callable:
    """Build the ASGI application closure over the injected ``deps``."""

    async def app(scope: dict, receive: Callable, send: Callable) -> None:
        if scope["type"] != "http":  # pragma: no cover - lifespan/ws not served
            return
        method = scope["method"]
        path = scope["path"]
        if method == "POST" and path == _TRANSCRIBE_PATH:
            await _handle_transcribe(deps, receive, send)
        elif method == "GET" and path.startswith(_STATUS_PREFIX):
            await _handle_status(deps, path, send)
        else:
            await _send_json(send, 404, {"error": "not found"})

    return app
