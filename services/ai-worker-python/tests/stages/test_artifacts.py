"""Unit tests for the pure artifact helpers (stages/artifacts.py)."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from fliphouse_worker.stages import artifacts


def test_sha256_file_matches_hashlib_streamed(tmp_path: Path) -> None:
    # > 1 MiB of varied bytes so the streaming loop iterates multiple chunks.
    data = bytes(range(256)) * 5000  # ~1.28 MiB
    target = tmp_path / "clip.bin"
    target.write_bytes(data)
    assert artifacts.sha256_file(target) == hashlib.sha256(data).hexdigest()


def test_sha256_file_handles_empty_file(tmp_path: Path) -> None:
    target = tmp_path / "empty.bin"
    target.write_bytes(b"")
    assert artifacts.sha256_file(target) == hashlib.sha256(b"").hexdigest()


def test_content_key_strips_trailing_slash() -> None:
    assert artifacts.content_key("score-abc/", "clips.json") == "score-abc/clips.json"
    assert artifacts.content_key("score-abc", "clips.json") == "score-abc/clips.json"


def test_content_key_unique_per_stage_and_hash() -> None:
    a = artifacts.content_key("transcode-h1", "proxy.mp4")
    b = artifacts.content_key("transcode-h2", "proxy.mp4")
    c = artifacts.content_key("reframe-h1", "proxy.mp4")
    assert a != b != c and a != c


def test_artifact_ref_returns_key_bytes_sha256(tmp_path: Path) -> None:
    data = b"\x00\x01\x02\x03payload"
    target = tmp_path / "proxy.mp4"
    target.write_bytes(data)
    ref = artifacts.artifact_ref("transcode-h1/proxy.mp4", target)
    assert ref == {
        "key": "transcode-h1/proxy.mp4",
        "bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
