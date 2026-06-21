"""Unit tests for the reframe stage handler (the renderer faked)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.reframe import reframe_handler

from ._fakes import FakeR2, make_request

_ONE_CLIP = {
    "schema_version": 1,
    "cost_usd_micros": 0,
    "clips": [
        {
            "rank": 0,
            "used_video": True,
            "candidate": {
                "title": "a",
                "start_time": 10.0,
                "end_time": 40.0,
                "llm_score": 70.0,
                "dsp_prior": 0.5,
                "text_excerpt": "x",
            },
            "scored": {
                "aggregate": 80.0,
                "sub_scores": {"hook": 80},
                "confidence": 4,
                "modalities_used": ["text"],
                "model_used": "g",
                "raw_usage": {},
            },
        }
    ],
}


def _clips_bytes(payload: dict) -> bytes:
    return json.dumps(payload).encode("utf-8")


def test_reframe_uploads_clips_and_manifest() -> None:
    r2 = FakeR2({"transcode-h0/proxy.mp4": b"v", "score-h0/clips.json": _clips_bytes(_ONE_CLIP)})
    req = make_request(
        "reframe", inputs={"source": "transcode-h0/proxy.mp4", "clips": "score-h0/clips.json"}
    )

    def fake_render(clips, src, out_dir, *a, **k):
        assert len(clips) == 1 and str(src).endswith("source.mp4")
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00\x01")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    out = reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    assert [a["key"] for a in out["outputs"]] == [
        "reframe-h1/clip_00.mp4",
        "reframe-h1/manifest.json",
    ]
    assert out["metrics"]["clip_count"] == 1
    assert r2.uploaded["reframe-h1/clip_00.mp4"] == b"\x00\x01"


def test_reframe_empty_clips_uploads_only_manifest() -> None:
    empty = {"schema_version": 1, "cost_usd_micros": 0, "clips": []}
    r2 = FakeR2({"p": b"v", "c": _clips_bytes(empty)})
    req = make_request("reframe", inputs={"source": "p", "clips": "c"})

    def fake_render(clips, src, out_dir, *a, **k):
        assert clips == []
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=0)

    out = reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    assert [a["key"] for a in out["outputs"]] == ["reframe-h1/manifest.json"]
    assert out["metrics"]["clip_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
