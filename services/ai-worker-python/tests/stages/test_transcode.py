"""Unit tests for the transcode stage handler (every impure seam faked)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fliphouse_worker.stages._types import StageDeps, _build_transcode_argv
from fliphouse_worker.stages.transcode import transcode_handler

from ._fakes import FakeR2, make_request


def test_transcode_argv_uses_libx264_veryfast_threads0() -> None:
    argv = _build_transcode_argv(Path("in.mp4"), Path("out.mp4"))
    # GPL x264 on the INTERNAL proxy only (founder-approved, never delivered).
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert "libopenh264" not in argv
    assert argv[argv.index("-preset") + 1] == "veryfast"
    assert argv[argv.index("-threads") + 1] == "0"
    assert argv[argv.index("-crf") + 1] == "23"
    # Still a 720p AAC +faststart proxy with the source/out wired in.
    assert "scale=-2:720" in argv
    assert argv[argv.index("-i") + 1] == "in.mp4"
    assert argv[-1] == "out.mp4"


def _deps(r2: FakeR2, *, ffmpeg=None, probe_duration=None) -> StageDeps:
    def stub_ffmpeg(src: Path, out: Path) -> None:
        assert Path(src).read_bytes() == b"raw-upload"  # got the downloaded source
        Path(out).write_bytes(b"720p-proxy")

    return StageDeps(
        r2=r2,
        transcode_ffmpeg=ffmpeg or stub_ffmpeg,
        probe_duration=probe_duration or (lambda src: 90.5),
    )


def test_transcode_uploads_proxy_with_integrity() -> None:
    r2 = FakeR2({"ingest/raw.mp4": b"raw-upload"})
    req = make_request("transcode", inputs={"source": "ingest/raw.mp4"})
    out = transcode_handler(req, _deps(r2))

    assert [a["key"] for a in out["outputs"]] == ["transcode-h1/proxy.mp4"]
    assert out["outputs"][0]["bytes"] == len(b"720p-proxy")
    assert len(out["outputs"][0]["sha256"]) == 64
    assert r2.uploaded["transcode-h1/proxy.mp4"] == b"720p-proxy"
    assert out["metrics"]["duration_ms"] >= 0


def test_transcode_probes_source_duration_for_billing() -> None:
    r2 = FakeR2({"ingest/raw.mp4": b"raw-upload"})
    req = make_request("transcode", inputs={"source": "ingest/raw.mp4"})
    probed: list[bytes] = []

    def fake_probe(src: Path) -> float:
        # Read inside the call (the workspace is cleaned up on handler exit).
        probed.append(Path(src).read_bytes())
        return 90.5  # seconds → 90500 ms (the PAYG billable quantity)

    out = transcode_handler(req, _deps(r2, probe_duration=fake_probe))

    # Probed the downloaded ORIGINAL source (not the proxy), and rounded to ms.
    assert probed == [b"raw-upload"]
    assert out["metrics"]["source_duration_ms"] == 90_500


def test_transcode_empty_output_is_fatal() -> None:
    r2 = FakeR2({"ingest/raw.mp4": b"raw-upload"})
    req = make_request("transcode", inputs={"source": "ingest/raw.mp4"})
    deps = _deps(r2, ffmpeg=lambda src, out: Path(out).write_bytes(b""))
    with pytest.raises(ValueError, match="no proxy output"):
        transcode_handler(req, deps)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
