"""Unit tests for the asr stage handler (extract_audio + transcribe faked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fliphouse_worker.stages._types import StageDeps, _default_transcribe
from fliphouse_worker.stages.asr import asr_handler
from fliphouse_worker.transcription import Segment, Transcript, Word, WordSegment

from ._fakes import FakeR2, make_request


def _transcript() -> Transcript:
    return Transcript(
        duration=10.0,
        language="ru",
        engine="gigaam-v3",
        segments=(Segment(0.0, 5.0, "привет"), Segment(5.0, 10.0, "мир")),
        word_segments=(
            WordSegment(0.0, 5.0, (Word(" привет", 0.0, 5.0),)),
            WordSegment(5.0, 10.0, (Word(" мир", 5.0, 10.0),)),
        ),
    )


def test_asr_emits_both_transcript_contracts() -> None:
    r2 = FakeR2({"transcode-h0/proxy.mp4": b"proxy"})
    req = make_request("asr", inputs={"source": "transcode-h0/proxy.mp4"})
    deps = StageDeps(
        r2=r2,
        extract_audio=lambda src, out: Path(out).write_bytes(b"wav"),
        transcribe=lambda wav, params: _transcript(),
    )
    out = asr_handler(req, deps)

    assert [a["key"] for a in out["outputs"]] == [
        "asr-h1/word_segments.json",
        "asr-h1/cascade_transcript.json",
    ]
    assert out["metrics"]["segment_count"] == 2

    cascade = json.loads(r2.uploaded["asr-h1/cascade_transcript.json"])
    assert [s["text"] for s in cascade["segments"]] == ["привет", "мир"]
    words = json.loads(r2.uploaded["asr-h1/word_segments.json"])
    assert words[0]["words"][0]["word"] == " привет"  # leading space (captacity) preserved


def test_asr_passes_params_to_transcribe() -> None:
    r2 = FakeR2({"k": b"proxy"})
    req = make_request("asr", inputs={"source": "k"}, params={"language": "en"})
    seen = {}

    def transcribe(wav: Path, params: dict) -> Transcript:
        seen["params"] = params
        return _transcript()

    asr_handler(
        req,
        StageDeps(
            r2=r2, extract_audio=lambda s, o: Path(o).write_bytes(b"w"), transcribe=transcribe
        ),
    )
    assert seen["params"] == {"language": "en"}


def test_default_transcribe_refuses_loud_when_gpu_lane_off() -> None:
    # GigaAM-v3 is the sole engine (GPU submit-and-park lane). The inline seam has
    # no engine, so reaching it must FAIL LOUD, never silently produce text.
    with pytest.raises(RuntimeError, match="GPU_ASR_ENABLED"):
        _default_transcribe(Path("audio.wav"), {})


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
