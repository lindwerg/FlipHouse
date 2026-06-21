"""Unit tests for the store stage handler (result.json assembly)."""

from __future__ import annotations

import json

import pytest

from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.store import store_handler

from ._fakes import FakeR2, make_request


def _manifest() -> dict:
    def entry(rank: int) -> dict:
        return {
            "rank": rank,
            "path": f"clip_0{rank}.mp4",
            "title": f"clip {rank}",
            "score": 80.0 - rank,
            "duration_s": 30.0,
            "width": 1080,
            "height": 1920,
        }

    return {"schema_version": 2, "clip_count": 2, "clips": [entry(0), entry(1)]}


def test_store_builds_result_with_derived_clip_keys() -> None:
    r2 = FakeR2({"reframe-h0/manifest.json": json.dumps(_manifest()).encode("utf-8")})
    req = make_request("store", inputs={"manifest": "reframe-h0/manifest.json"})

    out = store_handler(req, StageDeps(r2=r2))
    assert [a["key"] for a in out["outputs"]] == ["store-h1/result.json"]
    assert out["metrics"]["clip_count"] == 2

    result = json.loads(r2.uploaded["store-h1/result.json"])
    assert result["clip_count"] == 2
    assert result["clips"][0] == {
        "rank": 0,
        "key": "reframe-h0/clip_00.mp4",  # derived from the manifest input's prefix
        "title": "clip 0",
        "score": 80.0,
        "duration_s": 30.0,
        "width": 1080,
        "height": 1920,
    }
    assert result["clips"][1]["key"] == "reframe-h0/clip_01.mp4"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
