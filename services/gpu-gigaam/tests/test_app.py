"""ASGI app tests — drive the coroutine directly with fake receive/send."""

from __future__ import annotations

import asyncio
import json

from fliphouse_gigaam.app import AppDeps, create_app
from fliphouse_gigaam.orchestrator import TranscribeDeps
from fliphouse_gigaam.status_store import InMemoryStatusStore

from ._fakes import FakePoster, canned_payload, fake_workspace, make_fetch

SECRET = "test-secret"

VALID_BODY = {
    "request_id": "r1",
    "audio_url": "https://r2.example/audio.wav",
    "language": "ru",
    "webhook_url": "https://receiver.example/gpu/callback",
    "output_prefix": "intermediate/h/asr",
}


class _Sent:
    """Collects ASGI response events and exposes status + decoded JSON body."""

    def __init__(self) -> None:
        self.events: list[dict] = []

    async def __call__(self, event: dict) -> None:
        self.events.append(event)

    @property
    def status(self) -> int:
        return self.events[0]["status"]

    @property
    def json(self) -> dict:
        return json.loads(self.events[1]["body"])


def _receive_factory(body: bytes):
    sent = {"done": False}

    async def receive() -> dict:
        if sent["done"]:
            return {"type": "http.request", "body": b"", "more_body": False}
        sent["done"] = True
        return {"type": "http.request", "body": body, "more_body": False}

    return receive


def _make_app(tmp_path, store, poster, *, schedule):
    deps = TranscribeDeps(
        secret=SECRET,
        poster=poster,
        store=store,
        fetch_audio=make_fetch(),
        transcribe_audio=lambda path, lang: canned_payload(),
        workspace=lambda: fake_workspace(tmp_path),
        now=lambda: 1700000000,
    )
    return create_app(AppDeps(transcribe=deps, schedule=schedule))


def _run(app, scope, receive, send):
    asyncio.run(app(scope, receive, send))


def test_transcribe_returns_202_accepted_and_schedules(tmp_path):
    store = InMemoryStatusStore()
    poster = FakePoster()
    scheduled: list = []
    app = _make_app(tmp_path, store, poster, schedule=lambda job: scheduled.append(job))
    send = _Sent()

    _run(
        app,
        {"type": "http", "method": "POST", "path": "/transcribe"},
        _receive_factory(json.dumps(VALID_BODY).encode()),
        send,
    )

    assert send.status == 202
    assert send.json == {"request_id": "r1", "status": "accepted"}
    # Status marked processing synchronously, before the job runs.
    assert store.get("r1").status == "processing"
    # The work was scheduled, not run inline.
    assert len(scheduled) == 1


def test_scheduled_job_runs_full_pipeline(tmp_path):
    store = InMemoryStatusStore()
    poster = FakePoster()
    # Synchronous scheduler: run the job inline so we can assert the callback.
    app = _make_app(tmp_path, store, poster, schedule=lambda job: job())
    send = _Sent()

    _run(
        app,
        {"type": "http", "method": "POST", "path": "/transcribe"},
        _receive_factory(json.dumps(VALID_BODY).encode()),
        send,
    )

    assert send.status == 202
    assert store.get("r1").status == "succeeded"
    assert json.loads(poster.calls[0][1])["status"] == "succeeded"


def test_transcribe_invalid_body_returns_400(tmp_path):
    store = InMemoryStatusStore()
    app = _make_app(tmp_path, store, FakePoster(), schedule=lambda job: None)
    send = _Sent()

    bad = dict(VALID_BODY, audio_url="http://insecure/x")
    _run(
        app,
        {"type": "http", "method": "POST", "path": "/transcribe"},
        _receive_factory(json.dumps(bad).encode()),
        send,
    )

    assert send.status == 400
    assert store.get("r1") is None  # never scheduled


def test_transcribe_malformed_json_returns_400(tmp_path):
    app = _make_app(tmp_path, InMemoryStatusStore(), FakePoster(), schedule=lambda job: None)
    send = _Sent()
    _run(
        app,
        {"type": "http", "method": "POST", "path": "/transcribe"},
        _receive_factory(b"{not json"),
        send,
    )
    assert send.status == 400


def test_oversize_body_returns_400(tmp_path):
    app = _make_app(tmp_path, InMemoryStatusStore(), FakePoster(), schedule=lambda job: None)
    send = _Sent()

    big = b"x" * (1_048_576 + 1)

    async def receive() -> dict:
        return {"type": "http.request", "body": big, "more_body": False}

    _run(app, {"type": "http", "method": "POST", "path": "/transcribe"}, receive, send)
    assert send.status == 400


def test_multi_chunk_body_is_drained(tmp_path):
    store = InMemoryStatusStore()
    app = _make_app(tmp_path, store, FakePoster(), schedule=lambda job: None)
    send = _Sent()

    raw = json.dumps(VALID_BODY).encode()
    mid = len(raw) // 2
    parts = [
        {"type": "http.request", "body": raw[:mid], "more_body": True},
        {"type": "http.request", "body": raw[mid:], "more_body": False},
    ]
    idx = {"i": 0}

    async def receive() -> dict:
        event = parts[idx["i"]]
        idx["i"] += 1
        return event

    _run(app, {"type": "http", "method": "POST", "path": "/transcribe"}, receive, send)
    assert send.status == 202


def test_status_known_request(tmp_path):
    store = InMemoryStatusStore()
    store.mark_succeeded("r1")
    app = _make_app(tmp_path, store, FakePoster(), schedule=lambda job: None)
    send = _Sent()

    async def receive() -> dict:  # GET has no body
        return {"type": "http.request", "body": b"", "more_body": False}

    _run(app, {"type": "http", "method": "GET", "path": "/status/r1"}, receive, send)
    assert send.status == 200
    assert send.json == {"request_id": "r1", "status": "succeeded"}


def test_status_unknown_request_404(tmp_path):
    app = _make_app(tmp_path, InMemoryStatusStore(), FakePoster(), schedule=lambda job: None)
    send = _Sent()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    _run(app, {"type": "http", "method": "GET", "path": "/status/missing"}, receive, send)
    assert send.status == 404


def test_unknown_route_404(tmp_path):
    app = _make_app(tmp_path, InMemoryStatusStore(), FakePoster(), schedule=lambda job: None)
    send = _Sent()

    async def receive() -> dict:
        return {"type": "http.request", "body": b"", "more_body": False}

    _run(app, {"type": "http", "method": "GET", "path": "/health"}, receive, send)
    assert send.status == 404
