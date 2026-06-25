"""Unit tests for the caption stage handler (a pure forwarder post-SPD-1).

SPD-1 folded the per-word caption burn into the reframe encode, so the caption stage no
longer runs ffmpeg — it only FORWARDS the already-captioned reframe clips + manifest under
its own prefix so the publish finalizer's prefix wiring is unchanged. These tests pin the
forward behaviour: clips re-uploaded byte-identical, the manifest forwarded verbatim, and a
fail-CLOSED raise when a clip the manifest names is missing/empty in R2.
"""

from __future__ import annotations

import json

import pytest

from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.caption import caption_handler

from ._fakes import FakeR2, make_request

REFRAME_PREFIX = "intermediate/h0/reframe"


def _manifest(clips: list[dict]) -> dict:
    return {
        "schema_version": 2,
        "source": "uploads/a.mp4",
        "engine": "fliphouse-cpu-mediapipe-v1",
        "generated_at": "2026-06-22T00:00:00Z",
        "resolution": [1080, 1920],
        "clip_count": len(clips),
        "clips": clips,
    }


def _clip(rank: int, start: float, end: float) -> dict:
    return {
        "rank": rank,
        "score": 80.0,
        "sub_scores": {"hook": 8},
        "confidence": 4,
        "start_time": start,
        "end_time": end,
        "duration_s": round(end - start, 3),
        "width": 1080,
        "height": 1920,
        "path": f"clip_{rank:02d}.mp4",
        "title": "t",
        "used_video": True,
        "model_used": "g",
        "modalities_used": ["text"],
        "segment_count": 1,
        "caption_band": None,
    }


def _seed_r2(manifest: dict, clip_paths: list[str]) -> FakeR2:
    objects: dict[str, bytes] = {
        f"{REFRAME_PREFIX}/manifest.json": json.dumps(manifest).encode("utf-8"),
    }
    for path in clip_paths:
        objects[f"{REFRAME_PREFIX}/{path}"] = b"captioned-" + path.encode()
    return FakeR2(objects)


def _req() -> dict:
    return make_request(
        "caption",
        inputs={
            "manifest": f"{REFRAME_PREFIX}/manifest.json",
            "clips_prefix": REFRAME_PREFIX,
        },
        output_prefix="caption-h1",
    )


def test_forwards_each_clip_and_manifest_without_re_encode() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0), _clip(1, 30.0, 40.0)])
    r2 = _seed_r2(manifest, ["clip_00.mp4", "clip_01.mp4"])

    out = caption_handler(_req(), StageDeps(r2=r2))

    keys = sorted(a["key"] for a in out["outputs"])
    assert keys == [
        "caption-h1/clip_00.mp4",
        "caption-h1/clip_01.mp4",
        "caption-h1/manifest.json",
    ]
    # SPD-1: the already-captioned reframe bytes are forwarded VERBATIM (no re-encode).
    assert r2.uploaded["caption-h1/clip_00.mp4"] == b"captioned-clip_00.mp4"
    assert r2.uploaded["caption-h1/clip_01.mp4"] == b"captioned-clip_01.mp4"
    parsed = json.loads(r2.uploaded["caption-h1/manifest.json"].decode("utf-8"))
    assert parsed["clip_count"] == 2
    assert out["metrics"]["clip_count"] == 2
    # `captioned` counts delivered clips (the burn already happened upstream).
    assert out["metrics"]["captioned"] == 2


def test_manifest_forwarded_byte_identical() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    r2 = _seed_r2(manifest, ["clip_00.mp4"])

    caption_handler(_req(), StageDeps(r2=r2))

    forwarded = json.loads(r2.uploaded["caption-h1/manifest.json"].decode("utf-8"))
    assert forwarded == manifest  # clip windows + caption_band already drove the burn


def test_fail_closed_raises_when_named_clip_is_missing_from_r2() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    # The manifest names clip_00.mp4 but R2 has no such object → the download itself
    # raises (fatal); the stage aborts rather than silently dropping a paid clip.
    r2 = _seed_r2(manifest, [])
    with pytest.raises(KeyError):
        caption_handler(_req(), StageDeps(r2=r2))


def test_fail_closed_raises_when_clip_download_is_empty() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    r2 = _seed_r2(manifest, [])
    r2.objects[f"{REFRAME_PREFIX}/clip_00.mp4"] = b""  # present but empty
    with pytest.raises(Exception, match="no output"):
        caption_handler(_req(), StageDeps(r2=r2))


def test_empty_manifest_uploads_only_manifest() -> None:
    manifest = _manifest([])
    r2 = _seed_r2(manifest, [])

    out = caption_handler(_req(), StageDeps(r2=r2))
    assert [a["key"] for a in out["outputs"]] == ["caption-h1/manifest.json"]
    assert out["metrics"]["clip_count"] == 0
    assert out["metrics"]["captioned"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
