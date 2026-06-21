"""Unit tests for the caption/banner passthrough handler."""

from __future__ import annotations

import pytest

from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.passthrough import passthrough_handler

from ._fakes import FakeR2, make_request


def test_passthrough_copies_each_input_under_output_prefix() -> None:
    r2 = FakeR2(
        {
            "reframe-h0/clip_00.mp4": b"clip-bytes",
            "reframe-h0/manifest.json": b'{"clip_count":1}',
        }
    )
    req = make_request(
        "caption",
        inputs={"clip0": "reframe-h0/clip_00.mp4", "manifest": "reframe-h0/manifest.json"},
    )
    out = passthrough_handler(req, StageDeps(r2=r2))

    assert sorted(a["key"] for a in out["outputs"]) == [
        "caption-h1/clip_00.mp4",
        "caption-h1/manifest.json",
    ]
    assert r2.uploaded["caption-h1/clip_00.mp4"] == b"clip-bytes"  # bytes unchanged
    assert out["metrics"] == {
        "duration_ms": out["metrics"]["duration_ms"],
        "passthrough": 1,
        "output_count": 2,
    }
    assert out["metrics"]["duration_ms"] >= 0


def test_passthrough_no_inputs_is_empty() -> None:
    out = passthrough_handler(make_request("banner"), StageDeps(r2=FakeR2()))
    assert out["outputs"] == []
    assert out["metrics"]["output_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
