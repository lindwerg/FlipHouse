"""Unit tests for the caption stage handler (burn + probe + replace all faked)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.caption import DimensionMismatchError, caption_handler

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


def _clip(rank: int, start: float, end: float, *, caption_band: dict | None = None) -> dict:
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
        "caption_band": caption_band,
    }


def _word_segments(segs: list[dict]) -> bytes:
    return json.dumps(segs).encode("utf-8")


def _seed_r2(manifest: dict, word_segments: list[dict], clip_paths: list[str]) -> FakeR2:
    objects: dict[str, bytes] = {
        f"{REFRAME_PREFIX}/manifest.json": json.dumps(manifest).encode("utf-8"),
        f"{REFRAME_PREFIX}/word_segments.json": _word_segments(word_segments),
    }
    for path in clip_paths:
        objects[f"{REFRAME_PREFIX}/{path}"] = b"reframed-" + path.encode()
    return FakeR2(objects)


def _req() -> dict:
    return make_request(
        "caption",
        inputs={
            "manifest": f"{REFRAME_PREFIX}/manifest.json",
            "word_segments": f"{REFRAME_PREFIX}/word_segments.json",
            "clips_prefix": REFRAME_PREFIX,
        },
        output_prefix="caption-h1",
    )


def _ok_burn(captioned_bytes: bytes = b"captioned"):
    def burn(src: Path, ass_text: str, out: Path) -> None:
        # A real burn emits a non-empty file at out; assert it received real ASS.
        assert "[Script Info]" in ass_text
        out.write_bytes(captioned_bytes)

    return burn


def _ok_probe(src: Path) -> tuple[int, int]:
    return (1080, 1920)


def test_burns_each_clip_and_uploads_captioned_clips_plus_manifest() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0), _clip(1, 30.0, 40.0)])
    words = [
        {
            "start": 10.0,
            "end": 40.0,
            "words": [
                {"word": " привет", "start": 11.0, "end": 11.5},
                {"word": " мир", "start": 31.0, "end": 31.5},
            ],
        }
    ]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4", "clip_01.mp4"])
    deps = StageDeps(r2=r2, caption_burn=_ok_burn(), probe=_ok_probe)

    out = caption_handler(_req(), deps)

    keys = sorted(a["key"] for a in out["outputs"])
    assert keys == [
        "caption-h1/clip_00.mp4",
        "caption-h1/clip_01.mp4",
        "caption-h1/manifest.json",
    ]
    assert r2.uploaded["caption-h1/clip_00.mp4"] == b"captioned"
    # The uploaded manifest is valid JSON carrying both clips.
    parsed = json.loads(r2.uploaded["caption-h1/manifest.json"].decode("utf-8"))
    assert parsed["clip_count"] == 2
    assert out["metrics"]["clip_count"] == 2
    assert out["metrics"]["captioned"] == 2


def test_fail_open_copies_clip_through_unchanged_when_no_words_in_window() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    # The only word lies OUTSIDE [10,20) → no captions → copy-through.
    words = [{"start": 0.0, "end": 100.0, "words": [{"word": " late", "start": 90.0, "end": 90.5}]}]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4"])

    burned: list[str] = []

    def tracking_burn(src: Path, ass_text: str, out: Path) -> None:  # pragma: no cover
        burned.append(str(src))
        out.write_bytes(b"should-not-happen")

    deps = StageDeps(r2=r2, caption_burn=tracking_burn, probe=_ok_probe)
    out = caption_handler(_req(), deps)

    assert burned == []  # burn was never called (fail-open copy-through)
    # The original reframed bytes are forwarded verbatim.
    assert r2.uploaded["caption-h1/clip_00.mp4"] == b"reframed-clip_00.mp4"
    assert out["metrics"]["captioned"] == 0


def test_fail_closed_raises_when_burn_produces_empty_output() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    words = [{"start": 10.0, "end": 20.0, "words": [{"word": " hi", "start": 11.0, "end": 11.5}]}]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4"])

    def empty_burn(src: Path, ass_text: str, out: Path) -> None:
        out.write_bytes(b"")  # ffmpeg returned 0 but produced nothing

    deps = StageDeps(r2=r2, caption_burn=empty_burn, probe=_ok_probe)
    with pytest.raises(Exception, match="no output"):
        caption_handler(_req(), deps)


def test_fail_closed_raises_on_dimension_mismatch() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    words = [{"start": 10.0, "end": 20.0, "words": [{"word": " hi", "start": 11.0, "end": 11.5}]}]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4"])

    def wrong_probe(src: Path) -> tuple[int, int]:
        return (720, 1280)

    deps = StageDeps(r2=r2, caption_burn=_ok_burn(), probe=wrong_probe)
    with pytest.raises(DimensionMismatchError):
        caption_handler(_req(), deps)


def test_burn_exception_is_fatal_not_swallowed() -> None:
    manifest = _manifest([_clip(0, 10.0, 20.0)])
    words = [{"start": 10.0, "end": 20.0, "words": [{"word": " hi", "start": 11.0, "end": 11.5}]}]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4"])

    def boom_burn(src: Path, ass_text: str, out: Path) -> None:
        raise RuntimeError("ffmpeg exploded")

    deps = StageDeps(r2=r2, caption_burn=boom_burn, probe=_ok_probe)
    with pytest.raises(RuntimeError, match="exploded"):
        caption_handler(_req(), deps)


def test_passes_source_caption_band_into_the_ass_via_marginv() -> None:
    band = {"y_top": 1400, "y_bottom": 1500, "confidence": 0.9}
    manifest = _manifest([_clip(0, 10.0, 20.0, caption_band=band)])
    words = [{"start": 10.0, "end": 20.0, "words": [{"word": " hi", "start": 11.0, "end": 11.5}]}]
    r2 = _seed_r2(manifest, words, ["clip_00.mp4"])

    seen: dict[str, str] = {}

    def capture_burn(src: Path, ass_text: str, out: Path) -> None:
        seen["ass"] = ass_text
        out.write_bytes(b"captioned")

    deps = StageDeps(r2=r2, caption_burn=capture_burn, probe=_ok_probe)
    caption_handler(_req(), deps)

    # MarginV lifted above the source band (default 210 → larger).
    assert "Style: Caption," in seen["ass"]
    # 1920 - 1400 + 24 = 544 → that lifted MarginV appears in the Style line.
    assert ",40,40,544,1" in seen["ass"]


def test_empty_manifest_uploads_only_manifest() -> None:
    manifest = _manifest([])
    r2 = _seed_r2(manifest, [], [])
    deps = StageDeps(r2=r2, caption_burn=_ok_burn(), probe=_ok_probe)

    out = caption_handler(_req(), deps)
    assert [a["key"] for a in out["outputs"]] == ["caption-h1/manifest.json"]
    assert out["metrics"]["clip_count"] == 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
