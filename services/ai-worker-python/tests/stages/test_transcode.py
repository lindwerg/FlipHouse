"""Unit tests for the transcode stage handler (every impure seam faked)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from fliphouse_worker.stages._types import StageDeps, _build_transcode_argv
from fliphouse_worker.stages.transcode import transcode_handler

from ._fakes import FakeR2, make_request


def test_transcode_argv_uses_libx264_superfast_threads0() -> None:
    argv = _build_transcode_argv(Path("in.mp4"), Path("out.mp4"))
    # GPL x264 on the INTERNAL proxy only (founder-approved, never delivered).
    assert argv[argv.index("-c:v") + 1] == "libx264"
    assert "libopenh264" not in argv
    # SPD-3: the proxy is the long-pole CPU step + visually disposable, so the default
    # preset drops to superfast and crf rises to 26 to cut wall-clock further.
    assert argv[argv.index("-preset") + 1] == "superfast"
    assert argv[argv.index("-threads") + 1] == "0"
    assert argv[argv.index("-crf") + 1] == "26"
    # Still a 720p AAC +faststart proxy with the source/out wired in.
    assert "scale=-2:720" in argv
    assert argv[argv.index("-i") + 1] == "in.mp4"
    assert argv[-1] == "out.mp4"


def test_transcode_argv_proxy_knobs_are_env_overridable(monkeypatch) -> None:
    # SPD-3: re-tune the proxy encode on a busier box WITHOUT a deploy. The knobs are read
    # at module import, so reload the module under the patched env and rebuild the argv.
    import importlib

    monkeypatch.setenv("FH_PROXY_PRESET", "ultrafast")
    monkeypatch.setenv("FH_PROXY_CRF", "28")
    monkeypatch.setenv("FH_PROXY_THREADS", "2")
    import fliphouse_worker.stages._types as types_mod

    reloaded = importlib.reload(types_mod)
    try:
        argv = reloaded._build_transcode_argv(Path("in.mp4"), Path("out.mp4"))
        assert argv[argv.index("-preset") + 1] == "ultrafast"
        assert argv[argv.index("-crf") + 1] == "28"
        assert argv[argv.index("-threads") + 1] == "2"
    finally:
        monkeypatch.undo()
        importlib.reload(reloaded)  # restore module-level defaults for other tests


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


def test_transcode_probes_source_duration_for_billing(caplog) -> None:
    r2 = FakeR2({"ingest/raw.mp4": b"raw-upload"})
    req = make_request("transcode", inputs={"source": "ingest/raw.mp4"})
    probed: list[bytes] = []

    def fake_probe(src: Path) -> float:
        # Read inside the call (the workspace is cleaned up on handler exit).
        probed.append(Path(src).read_bytes())
        return 90.5  # seconds → 90500 ms (the PAYG billable quantity)

    with caplog.at_level(logging.INFO):
        out = transcode_handler(req, _deps(r2, probe_duration=fake_probe))

    # Probed the downloaded ORIGINAL source (not the proxy), and rounded to ms.
    assert probed == [b"raw-upload"]
    assert out["metrics"]["source_duration_ms"] == 90_500
    # OBS-1: the probed duration is surfaced at INFO for live diagnosability.
    assert any("probed source duration: 90500 ms" in r.message for r in caplog.records)


def test_transcode_empty_output_is_fatal() -> None:
    r2 = FakeR2({"ingest/raw.mp4": b"raw-upload"})
    req = make_request("transcode", inputs={"source": "ingest/raw.mp4"})
    deps = _deps(r2, ffmpeg=lambda src, out: Path(out).write_bytes(b""))
    with pytest.raises(ValueError, match="no proxy output"):
        transcode_handler(req, deps)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
