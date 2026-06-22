"""Unit tests for the asr-finalize handler (GigaAM raw payload → R2 contracts).

The GPU GigaAM lane delivers a raw payload via webhook; ``asr-finalize`` downloads
it from R2, validates it (fail-loud), normalizes it, and uploads the two canonical
contracts + a ``_COMPLETE`` sentinel written LAST. Idempotent: a present sentinel
short-circuits the whole thing.
"""

from __future__ import annotations

import json

import pytest

from fliphouse_worker.cli import _dispatch
from fliphouse_worker.stages import build_handlers
from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.asr_finalize import (
    COMPLETE_SENTINEL_NAME,
    asr_finalize_handler,
)
from fliphouse_worker.transcription import GigaamPayloadError

from ._fakes import FakeR2

_RAW = {
    "duration": 2.0,
    "language": "ru",
    "segments": [
        {
            "start": 0.0,
            "end": 2.0,
            "words": [
                {"word": "Я", "start": 0.0, "end": 0.4},
                {"word": "потерял", "start": 0.4, "end": 1.2},
                {"word": "миллион", "start": 1.2, "end": 2.0},
            ],
        },
    ],
}


def _request(
    *,
    raw_key: str = "intermediate/h1/asr/_raw_gigaam.json",
    prefix: str = "intermediate/h1/asr",
    engine: str = "gigaam-v3",
) -> dict:
    return {"rawPayloadKey": raw_key, "outputPrefix": prefix, "engine": engine}


def _deps_with_raw(raw: dict, *, prefix_objects: dict[str, bytes] | None = None) -> FakeR2:
    objects = {"intermediate/h1/asr/_raw_gigaam.json": json.dumps(raw).encode("utf-8")}
    objects.update(prefix_objects or {})
    return FakeR2(objects)


def test_finalize_uploads_both_contracts_and_sentinel_last() -> None:
    r2 = _deps_with_raw(_RAW)
    out = asr_finalize_handler(_request(), StageDeps(r2=r2))

    assert set(r2.uploaded) == {
        "intermediate/h1/asr/cascade_transcript.json",
        "intermediate/h1/asr/word_segments.json",
        f"intermediate/h1/asr/{COMPLETE_SENTINEL_NAME}",
    }
    # The two canonical contracts are emitted as ArtifactRefs (sentinel excluded).
    assert [a["key"] for a in out["outputs"]] == [
        "intermediate/h1/asr/word_segments.json",
        "intermediate/h1/asr/cascade_transcript.json",
    ]
    assert out["metrics"]["segment_count"] == 1
    assert out["metrics"]["skipped"] == 0


def test_finalize_cascade_and_word_contracts_match_normalize() -> None:
    r2 = _deps_with_raw(_RAW)
    asr_finalize_handler(_request(), StageDeps(r2=r2))

    cascade = json.loads(r2.uploaded["intermediate/h1/asr/cascade_transcript.json"])
    assert cascade["engine"] == "gigaam-v3"
    assert cascade["duration"] == 2.0
    assert cascade["segments"][0]["text"] == "Я потерял миллион"

    words = json.loads(r2.uploaded["intermediate/h1/asr/word_segments.json"])
    # Clean GigaAM tokens gained the leading space via normalize (captacity).
    assert [w["word"] for w in words[0]["words"]] == [" Я", " потерял", " миллион"]


def test_finalize_uses_request_engine_label() -> None:
    r2 = _deps_with_raw(_RAW)
    asr_finalize_handler(_request(engine="gigaam-v3-test"), StageDeps(r2=r2))
    cascade = json.loads(r2.uploaded["intermediate/h1/asr/cascade_transcript.json"])
    assert cascade["engine"] == "gigaam-v3-test"


def test_finalize_default_engine_when_absent() -> None:
    r2 = _deps_with_raw(_RAW)
    req = {"rawPayloadKey": "intermediate/h1/asr/_raw_gigaam.json", "outputPrefix": "out"}
    r2.objects["intermediate/h1/asr/_raw_gigaam.json"] = json.dumps(_RAW).encode("utf-8")
    asr_finalize_handler(req, StageDeps(r2=r2))
    cascade = json.loads(r2.uploaded["out/cascade_transcript.json"])
    assert cascade["engine"] == "gigaam-v3"


def test_finalize_is_idempotent_when_sentinel_present() -> None:
    r2 = _deps_with_raw(
        _RAW,
        prefix_objects={f"intermediate/h1/asr/{COMPLETE_SENTINEL_NAME}": b"done"},
    )
    out = asr_finalize_handler(_request(), StageDeps(r2=r2))
    # No re-upload at all; the skip is reported in metrics.
    assert r2.uploaded == {}
    assert out["outputs"] == []
    assert out["metrics"]["skipped"] == 1


def test_finalize_bad_payload_raises_fatal_value_error() -> None:
    # A word missing its "word" key must surface as a fatal GigaamPayloadError
    # (ValueError) so the dispatcher does not retry an unfixable payload.
    bad = {"duration": 1.0, "segments": [{"words": [{"start": 0.0, "end": 1.0}]}]}
    r2 = _deps_with_raw(bad)
    with pytest.raises(GigaamPayloadError):
        asr_finalize_handler(_request(), StageDeps(r2=r2))


def test_finalize_missing_raw_payload_key_is_value_error() -> None:
    r2 = FakeR2()
    with pytest.raises(ValueError, match="rawPayloadKey"):
        asr_finalize_handler({"outputPrefix": "intermediate/h1/asr"}, StageDeps(r2=r2))


def test_finalize_missing_output_prefix_is_value_error() -> None:
    r2 = _deps_with_raw(_RAW)
    with pytest.raises(ValueError, match="outputPrefix"):
        asr_finalize_handler(
            {"rawPayloadKey": "intermediate/h1/asr/_raw_gigaam.json"}, StageDeps(r2=r2)
        )


def test_finalize_round_trips_through_dispatch_as_success() -> None:
    # Reached via the same CLI dispatch path the Node side spawns
    # (`python -m fliphouse_worker.cli asr-finalize`): success envelope + numeric metrics.
    r2 = _deps_with_raw(_RAW)
    handlers = build_handlers(StageDeps(r2=r2))
    result = _dispatch.dispatch("asr-finalize", _request(), handlers)
    assert result["ok"] is True
    assert result["metrics"]["segment_count"] == 1
    assert {a["key"] for a in result["outputs"]} == {
        "intermediate/h1/asr/word_segments.json",
        "intermediate/h1/asr/cascade_transcript.json",
    }


def test_finalize_bad_payload_dispatches_as_fatal_value_error() -> None:
    bad = {"duration": 1.0, "segments": [{"words": [{"start": 0.0, "end": 1.0}]}]}
    r2 = _deps_with_raw(bad)
    handlers = build_handlers(StageDeps(r2=r2))
    result = _dispatch.dispatch("asr-finalize", _request(), handlers)
    assert result["ok"] is False
    assert (result["kind"], result["code"]) == ("fatal", "VALUE_ERROR")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
