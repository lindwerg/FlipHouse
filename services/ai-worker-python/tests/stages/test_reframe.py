"""Unit tests for the reframe stage handler (the renderer faked)."""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from fliphouse_worker.captioning.ass import (
    CONTRAST_BAND_BS3,
    CONTRAST_BAND_TRANSLUCENT,
    DEFAULT_PRESET,
)
from fliphouse_worker.stages._types import StageDeps
from fliphouse_worker.stages.reframe import (
    _select_caption_preset,
    build_caption_ass_fn,
    reframe_handler,
)

from ._fakes import FakeR2, make_request

_WORD_SEGMENTS = [
    {"start": 10.0, "end": 11.0, "words": [{"word": " привет", "start": 10.0, "end": 10.5}]},
]


def _word_segments_bytes() -> bytes:
    return json.dumps(_WORD_SEGMENTS).encode("utf-8")


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


def test_reframe_threads_scene_cut_times_to_render() -> None:
    payload = {**_ONE_CLIP, "schema_version": 2, "scene_cut_times": [15.0, 33.5]}
    r2 = FakeR2({"p": b"v", "c": _clips_bytes(payload)})
    req = make_request("reframe", inputs={"source": "p", "clips": "c"})
    seen = {}

    def fake_render(clips, src, out_dir, scene_cut_times=(), *a, **k):
        seen["cuts"] = scene_cut_times
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    assert seen["cuts"] == (15.0, 33.5)  # source-absolute cuts reach the renderer


def test_reframe_defaults_scene_cut_times_for_v1_clips_json() -> None:
    # A v1 clips.json (no scene_cut_times) must reframe with () — no crash, no snap.
    r2 = FakeR2({"p": b"v", "c": _clips_bytes(_ONE_CLIP)})
    req = make_request("reframe", inputs={"source": "p", "clips": "c"})
    seen = {}

    def fake_render(clips, src, out_dir, scene_cut_times=(), *a, **k):
        seen["cuts"] = scene_cut_times
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    assert seen["cuts"] == ()


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


def test_reframe_threads_caption_ass_fn_from_word_segments() -> None:
    # SPD-1: word_segments rides into reframe and a per-clip CaptionAssFn is injected so
    # the per-word caption .ass is burned in the SAME reframe encode (single pass).
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "score-h0/clips.json": _clips_bytes(_ONE_CLIP),
            "asr-h0/word_segments.json": _word_segments_bytes(),
        }
    )
    req = make_request(
        "reframe",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "clips": "score-h0/clips.json",
            "word_segments": "asr-h0/word_segments.json",
        },
    )
    seen = {}

    def fake_render(clips, src, out_dir, scene_cut_times=(), *, _caption_ass_fn=None, **k):
        seen["ass_fn"] = _caption_ass_fn
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    ass_fn = seen["ass_fn"]
    assert ass_fn is not None
    # A clip window that contains the word yields a real ASS doc; an empty window → None.
    assert ass_fn(10.0, 40.0, None) is not None
    assert "привет" in ass_fn(10.0, 40.0, None)
    assert ass_fn(100.0, 130.0, None) is None


def test_reframe_caption_ass_fn_fails_open_without_word_segments() -> None:
    # word_segments is FAIL-OPEN: a request without it still renders (uncaptioned clips).
    r2 = FakeR2({"p": b"v", "c": _clips_bytes(_ONE_CLIP)})
    req = make_request("reframe", inputs={"source": "p", "clips": "c"})
    seen = {}

    def fake_render(clips, src, out_dir, scene_cut_times=(), *, _caption_ass_fn=None, **k):
        seen["ass_fn"] = _caption_ass_fn
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    # The fn is present but yields None for every window (no words) → uncaptioned clips.
    assert seen["ass_fn"](10.0, 40.0, None) is None


def _render_one_clip(out_dir: Path) -> SimpleNamespace:
    (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
    (Path(out_dir) / "manifest.json").write_bytes(b"{}")
    return SimpleNamespace(clip_count=1)


def test_reframe_records_caption_coverage_metrics() -> None:
    # P3-C4: captions densely covering the clip window → high coverage, no dropout flag.
    dense = [
        {
            "start": 10.0,
            "end": 40.0,
            "words": [
                {"word": " a", "start": 10.0, "end": 25.0},
                {"word": " b", "start": 25.0, "end": 40.0},
            ],
        }
    ]
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "score-h0/clips.json": _clips_bytes(_ONE_CLIP),
            "asr-h0/word_segments.json": json.dumps(dense).encode("utf-8"),
        }
    )
    req = make_request(
        "reframe",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "clips": "score-h0/clips.json",
            "word_segments": "asr-h0/word_segments.json",
        },
    )
    out = reframe_handler(
        req, StageDeps(r2=r2, render=lambda c, s, o, *a, **k: _render_one_clip(o))
    )
    caps = out["metrics"]["captions"]
    assert caps[0]["rank"] == 0
    assert caps[0]["caption_coverage"] > 0.9
    assert caps[0]["speech_scored"] is True
    assert caps[0]["caption_dropout"] is False


def test_reframe_flags_caption_dropout_on_off_by_one_but_still_ships() -> None:
    # A speech-scored clip (text_excerpt="x") whose captions fall OUTSIDE the window
    # (absolute-vs-relative off-by-one) → coverage 0.0, flagged, but the clip still ships.
    off_window = [
        {"start": 0.0, "end": 200.0, "words": [{"word": " a", "start": 100.0, "end": 101.0}]}
    ]
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "score-h0/clips.json": _clips_bytes(_ONE_CLIP),
            "asr-h0/word_segments.json": json.dumps(off_window).encode("utf-8"),
        }
    )
    req = make_request(
        "reframe",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "clips": "score-h0/clips.json",
            "word_segments": "asr-h0/word_segments.json",
        },
    )
    out = reframe_handler(
        req, StageDeps(r2=r2, render=lambda c, s, o, *a, **k: _render_one_clip(o))
    )
    caps = out["metrics"]["captions"]
    assert caps[0]["caption_coverage"] == 0.0
    assert caps[0]["speech_scored"] is True
    assert caps[0]["caption_dropout"] is True
    assert any(a["key"].endswith("clip_00.mp4") for a in out["outputs"])  # NOT blocked


def test_reframe_does_not_flag_dropout_for_a_speechless_clip() -> None:
    # No transcript excerpt → speech_scored False → never flagged, even at 0 coverage.
    speechless = json.loads(json.dumps(_ONE_CLIP))
    speechless["clips"][0]["candidate"]["text_excerpt"] = "   "
    r2 = FakeR2({"p": b"v", "c": _clips_bytes(speechless)})
    req = make_request("reframe", inputs={"source": "p", "clips": "c"})
    out = reframe_handler(
        req, StageDeps(r2=r2, render=lambda c, s, o, *a, **k: _render_one_clip(o))
    )
    caps = out["metrics"]["captions"]
    assert caps[0]["speech_scored"] is False
    assert caps[0]["caption_dropout"] is False


def test_build_caption_ass_fn_uses_source_band() -> None:
    # The band lifts the caption margin; a non-None band must be honoured by the builder.
    ass_fn = build_caption_ass_fn(_WORD_SEGMENTS)
    with_band = ass_fn(10.0, 40.0, {"y_top": 900})
    without_band = ass_fn(10.0, 40.0, None)
    assert with_band is not None and without_band is not None
    assert with_band != without_band  # the band changed MarginV → a different ASS doc


# --- P3-A6: caption preset selection + forwarding ---


def test_build_caption_ass_fn_default_preset_is_byte_identical() -> None:
    # No preset → DEFAULT_PRESET → today's caption bytes (BorderStyle column stays 1).
    explicit = build_caption_ass_fn(_WORD_SEGMENTS, preset=DEFAULT_PRESET)(10.0, 40.0, None)
    implicit = build_caption_ass_fn(_WORD_SEGMENTS)(10.0, 40.0, None)
    assert explicit == implicit
    assert ",0,0,1,4,2,2," in implicit


def test_build_caption_ass_fn_forwards_selected_preset_into_ass() -> None:
    out = build_caption_ass_fn(_WORD_SEGMENTS, preset=CONTRAST_BAND_BS3)(10.0, 40.0, None)
    assert out is not None
    assert ",0,0,3,8,0,2," in out  # BorderStyle=3 box → distinct Style row


@pytest.mark.parametrize(
    ("req", "expected"),
    [
        ({"captionPreset": "band"}, CONTRAST_BAND_BS3),
        ({"captionPreset": "band_translucent"}, CONTRAST_BAND_TRANSLUCENT),
        ({"captionPreset": "nope"}, DEFAULT_PRESET),  # unknown → fail-open default
        ({}, DEFAULT_PRESET),  # missing → fail-open default
        ({"captionPreset": 7}, DEFAULT_PRESET),  # non-string → fail-open default
    ],
)
def test_select_caption_preset_resolves_or_fails_open(req: dict, expected: object) -> None:
    assert _select_caption_preset(req) is expected


def test_reframe_handler_threads_selected_preset_into_render() -> None:
    r2 = FakeR2(
        {
            "transcode-h0/proxy.mp4": b"v",
            "score-h0/clips.json": _clips_bytes(_ONE_CLIP),
            "asr-h0/word_segments.json": _word_segments_bytes(),
        }
    )
    req = make_request(
        "reframe",
        inputs={
            "source": "transcode-h0/proxy.mp4",
            "clips": "score-h0/clips.json",
            "word_segments": "asr-h0/word_segments.json",
        },
    )
    req["captionPreset"] = "band"
    seen = {}

    def fake_render(clips, src, out_dir, scene_cut_times=(), *, _caption_ass_fn=None, **k):
        seen["ass_fn"] = _caption_ass_fn
        (Path(out_dir) / "clip_00.mp4").write_bytes(b"\x00")
        (Path(out_dir) / "manifest.json").write_bytes(b"{}")
        return SimpleNamespace(clip_count=1)

    reframe_handler(req, StageDeps(r2=r2, render=fake_render))
    ass = seen["ass_fn"](10.0, 40.0, None)
    assert ass is not None and ",0,0,3,8,0,2," in ass  # selected band reached the renderer


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
