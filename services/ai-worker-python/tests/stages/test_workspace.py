"""Unit tests for the per-job workspace + R2 input/output marshalling."""

from __future__ import annotations

import pytest

from fliphouse_worker.stages import workspace

from ._fakes import FakeR2, make_request


def test_job_workspace_removed_after_exit() -> None:
    captured = {}
    with workspace.job_workspace(make_request("transcode")) as ws:
        assert ws.is_dir()
        captured["ws"] = ws
    assert not captured["ws"].exists()


def test_job_workspace_removed_on_exception() -> None:
    captured = {}
    with pytest.raises(RuntimeError, match="boom"):
        with workspace.job_workspace(make_request("asr")) as ws:
            captured["ws"] = ws
            raise RuntimeError("boom")
    assert not captured["ws"].exists()


def test_download_inputs_fetches_required_and_preserves_suffix() -> None:
    r2 = FakeR2({"score-h0/proxy.mp4": b"video-bytes", "score-h0/cascade_transcript.json": b"{}"})
    req = make_request(
        "score",
        inputs={
            "source": "score-h0/proxy.mp4",
            "transcript": "score-h0/cascade_transcript.json",
        },
    )
    with workspace.job_workspace(req) as ws:
        paths = workspace.download_inputs(r2, req, ws, required=("source", "transcript"))
        assert paths["source"].name == "source.mp4"
        assert paths["transcript"].name == "transcript.json"
        assert paths["source"].read_bytes() == b"video-bytes"


def test_download_inputs_missing_required_is_value_error() -> None:
    req = make_request("score", inputs={"source": "k"})
    with workspace.job_workspace(req) as ws:
        with pytest.raises(ValueError, match="missing required inputs"):
            workspace.download_inputs(FakeR2(), req, ws, required=("source", "transcript"))


def test_download_inputs_ignores_unrequired_inputs() -> None:
    r2 = FakeR2({"k_src": b"v"})
    req = make_request("transcode", inputs={"source": "k_src", "junk": "k_junk"})
    with workspace.job_workspace(req) as ws:
        paths = workspace.download_inputs(r2, req, ws, required=("source",))
        assert set(paths) == {"source"}


def test_upload_outputs_returns_sha256_and_bytes_for_all() -> None:
    r2 = FakeR2()
    with workspace.job_workspace(make_request("reframe")) as ws:
        clip = ws / "clip_000.mp4"
        clip.write_bytes(b"\x00\x01\x02")
        manifest = ws / "manifest.json"
        manifest.write_bytes(b"{}")
        refs = workspace.upload_outputs(r2, "reframe-h1", [clip, manifest])
    assert [r["key"] for r in refs] == ["reframe-h1/clip_000.mp4", "reframe-h1/manifest.json"]
    assert refs[0]["bytes"] == 3 and len(refs[0]["sha256"]) == 64
    assert r2.uploaded["reframe-h1/manifest.json"] == b"{}"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
