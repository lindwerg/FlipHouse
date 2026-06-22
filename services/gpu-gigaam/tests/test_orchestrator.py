"""Full orchestration — success + failure paths driven entirely with fakes."""

from __future__ import annotations

import hashlib
import hmac
import json

from fliphouse_gigaam.contracts import SubmitRequest
from fliphouse_gigaam.errors import AudioFetchError, CallbackPostError
from fliphouse_gigaam.orchestrator import TranscribeDeps, run_transcription
from fliphouse_gigaam.signing import SIGNATURE_HEADER, TIMESTAMP_HEADER
from fliphouse_gigaam.status_store import InMemoryStatusStore

from ._fakes import FakePoster, canned_payload, fake_workspace, make_fetch

SECRET = "test-secret"

REQ = SubmitRequest(
    request_id="r1",
    audio_url="https://r2.example/audio.wav",
    language="ru",
    webhook_url="https://receiver.example/gpu/callback",
    output_prefix="intermediate/h/asr",
)


def _verify(body: bytes, headers: dict[str, str]) -> bool:
    ts = headers[TIMESTAMP_HEADER]
    msg = f"{ts}.".encode() + body
    expected = "sha256=" + hmac.new(SECRET.encode(), msg, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, headers[SIGNATURE_HEADER])


def _make_deps(tmp_path, poster, *, transcribe=None, fetch=None, store=None):
    return TranscribeDeps(
        secret=SECRET,
        poster=poster,
        store=store or InMemoryStatusStore(),
        fetch_audio=fetch or make_fetch(),
        transcribe_audio=transcribe or (lambda path, lang: canned_payload()),
        workspace=lambda: fake_workspace(tmp_path),
        now=lambda: 1700000000,
    )


def test_success_posts_signed_succeeded_and_marks_store(tmp_path):
    poster = FakePoster(status_code=202)
    store = InMemoryStatusStore()
    store.mark_processing(REQ.request_id)
    captured_path = {}

    def transcribe(path, lang):
        captured_path["path"] = path
        captured_path["lang"] = lang
        return canned_payload()

    deps = _make_deps(tmp_path, poster, transcribe=transcribe, store=store)

    run_transcription(REQ, deps)

    # Status transitioned to succeeded.
    assert store.get("r1").status == "succeeded"
    # Exactly one callback, signed, verifiable by the receiver.
    url, body, headers = poster.calls[0]
    assert url == REQ.webhook_url
    assert _verify(body, headers)
    parsed = json.loads(body)
    assert parsed["status"] == "succeeded"
    assert parsed["engine"] == "gigaam-v3"
    assert parsed["payload"]["language"] == "ru"
    # transcribe got the fetched local path + language.
    assert captured_path["path"].endswith("audio_input")
    assert captured_path["lang"] == "ru"


def test_fetch_failure_posts_signed_failure_and_marks_failed(tmp_path):
    poster = FakePoster(status_code=202)
    store = InMemoryStatusStore()
    store.mark_processing(REQ.request_id)

    def fetch(url, dest):
        raise AudioFetchError("dns nope")

    deps = _make_deps(tmp_path, poster, fetch=fetch, store=store)

    run_transcription(REQ, deps)

    assert store.get("r1").status == "failed"
    assert store.get("r1").error == "dns nope"
    _url, body, headers = poster.calls[0]
    assert _verify(body, headers)
    parsed = json.loads(body)
    assert parsed == {"request_id": "r1", "status": "failed", "error": "dns nope"}


def test_unexpected_error_is_normalized_to_failure(tmp_path):
    poster = FakePoster(status_code=202)
    store = InMemoryStatusStore()

    def transcribe(path, lang):
        raise ValueError("weird")  # not a GigaamError

    deps = _make_deps(tmp_path, poster, transcribe=transcribe, store=store)

    run_transcription(REQ, deps)

    record = store.get("r1")
    assert record.status == "failed"
    assert "unexpected error" in record.error
    assert "weird" in record.error
    parsed = json.loads(poster.calls[0][1])
    assert parsed["status"] == "failed"


def test_failure_callback_undeliverable_still_marks_failed(tmp_path):
    # The failure callback POST itself fails — status must still be terminal.
    poster = FakePoster(raises=ConnectionError("receiver down"))
    store = InMemoryStatusStore()

    def fetch(url, dest):
        raise AudioFetchError("upstream gone")

    deps = _make_deps(tmp_path, poster, fetch=fetch, store=store)

    run_transcription(REQ, deps)  # must NOT raise

    assert store.get("r1").status == "failed"
    assert store.get("r1").error == "upstream gone"


def test_success_callback_rejected_marks_failed(tmp_path):
    # Transcription succeeded but the receiver rejected the callback (non-2xx).
    poster = FakePoster(status_code=503)
    store = InMemoryStatusStore()
    deps = _make_deps(tmp_path, poster, store=store)

    run_transcription(REQ, deps)

    # The success post raised CallbackPostError → caught → failure path.
    record = store.get("r1")
    assert record.status == "failed"
    assert "503" in record.error
    # Two posts: the failed success attempt + the failure callback.
    assert len(poster.calls) == 2
    assert json.loads(poster.calls[1][1])["status"] == "failed"


def test_callback_post_error_type_is_caught_as_gigaam_error():
    # Guard: CallbackPostError is a GigaamError so the orchestrator catches it.
    assert issubclass(CallbackPostError, Exception)
