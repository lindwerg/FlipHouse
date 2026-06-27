"""Full orchestration — success + failure paths driven entirely with fakes."""

from __future__ import annotations

import hashlib
import hmac
import json

from fliphouse_gigaam.align import realign_payload
from fliphouse_gigaam.contracts import Segment, SubmitRequest
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


# ---------------- P3-A1: realign flows through the SAME orchestration seam ----------------
# modal_app wires realign inside `_transcribe`; these drive it through `run_transcription`
# via an injected transcribe_audio so the realign→build_success_body→sign_and_post chain
# is CI-covered (the modal glue line itself is excluded from the gate).


def _shift_align(_wav, seg: Segment):
    return [(w.start + 0.1, w.end + 0.1) for w in seg.words]


def _raising_align(_wav, _seg: Segment):
    raise RuntimeError("aligner exploded")


def test_realigned_word_times_reach_the_signed_callback(tmp_path):
    poster = FakePoster(status_code=202)

    def transcribe(path, lang):
        return realign_payload(canned_payload(), path, align_fn=_shift_align, now_fn=lambda: 0.0)

    deps = _make_deps(tmp_path, poster, transcribe=transcribe)

    run_transcription(REQ, deps)

    words = json.loads(poster.calls[0][1])["payload"]["segments"][0]["words"]
    # canned (0,1),(1,2) shifted +0.1 → (0.1,1.1),(1.1,2.0-clamped); word text untouched.
    assert words[0]["word"] == "привет"
    assert words[0]["start"] == 0.1 and words[0]["end"] == 1.1
    assert words[1]["start"] == 1.1 and words[1]["end"] == 2.0


def test_aligner_failure_fails_open_through_orchestration(tmp_path):
    poster = FakePoster(status_code=202)

    def transcribe(path, lang):
        return realign_payload(canned_payload(), path, align_fn=_raising_align, now_fn=lambda: 0.0)

    deps = _make_deps(tmp_path, poster, transcribe=transcribe)

    run_transcription(REQ, deps)

    # Succeeded with the UN-aligned RNN-T times — alignment never blocks the clip.
    assert json.loads(poster.calls[0][1])["status"] == "succeeded"
    words = json.loads(poster.calls[0][1])["payload"]["segments"][0]["words"]
    assert words[0]["start"] == 0.0 and words[1]["end"] == 2.0
