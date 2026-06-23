"""render — pure argv/filtergraph builders + the orchestrator with every seam faked."""

from pathlib import Path

import pytest

from fliphouse_worker.clipping import render as render_mod
from fliphouse_worker.clipping.crop_geometry import (
    BLURPAD_MODE,
    CROP_MODE,
    GENERAL_MARK,
    TRACK_MARK,
    CropBox,
    CropKeyframe,
    CropTrajectory,
)
from fliphouse_worker.clipping.render import (
    ClipDurationError,
    CropModeError,
    DimensionMismatchError,
    RenderOutputError,
    _blurpad_graph_for,
    _build_blurpad_filtergraph,
    _build_concat_list,
    _build_concat_mux_argv,
    _build_render_argv,
    _build_video_render_argv,
    _timeout_for,
    _write_concat_list,
    _write_manifest_json,
    render_vertical_clips,
)
from fliphouse_worker.clipping.segments import RenderSegment
from fliphouse_worker.engine.cascade import SelectedClip
from fliphouse_worker.engine.recall import CandidateClip
from fliphouse_worker.scoring import ScoredClip

# ---- fixtures / fakes ----


def _clip(
    rank: int, start: float = 10.0, end: float = 55.0, aggregate: float = 80.0
) -> SelectedClip:
    candidate = CandidateClip(
        title=f"clip {rank}",
        start_time=start,
        end_time=end,
        llm_score=70.0,
        dsp_prior=0.5,
        text_excerpt="…",
    )
    scored = ScoredClip(
        aggregate=aggregate,
        sub_scores={
            "hook": 90,
            "emotion": 82,
            "payoff": 88,
            "visual": 84,
            "audio": 80,
            "pacing": 86,
        },
        confidence=90,
        modalities_used=["text", "video", "audio"],
        model_used="google/gemini-3.5-flash",
        raw_usage={},
    )
    return SelectedClip(candidate=candidate, scored=scored, rank=rank, used_video=True)


class _FakeSelector:
    """Returns a fixed trajectory and records every call's args."""

    def __init__(self, trajectory: CropTrajectory) -> None:
        self._traj = trajectory
        self.calls: list[tuple] = []

    def select_speaker_region(self, src, start, end, scene_cut_times):
        self.calls.append((src, start, end, tuple(scene_cut_times)))
        return self._traj


def _track_traj() -> CropTrajectory:
    return CropTrajectory(
        keyframes=(CropKeyframe(0.0, 960.0, TRACK_MARK),),
        source_width=1920,
        source_height=1080,
    )


def _general_traj() -> CropTrajectory:
    return CropTrajectory(
        keyframes=(CropKeyframe(0.0, None, GENERAL_MARK),),
        source_width=1920,
        source_height=1080,
    )


def _general_traj_for_segments() -> CropTrajectory:
    """A trajectory whose source dims feed the blur-pad boxes of a faked split."""
    return CropTrajectory(
        keyframes=(CropKeyframe(0.0, None, GENERAL_MARK),),
        source_width=1920,
        source_height=1080,
    )


def _three_blurpad_segments_fn(traj: CropTrajectory, clip_duration: float):
    """Inject a 3-way blur-pad split to exercise the video-only + concat machinery.

    The live ``_default_segments_fn`` always yields ONE full-frame blur-pad segment
    (founder mandate: never crop); this seam fakes a multi-segment split so the
    concat path stays covered with all-blur-pad segments.
    """
    box = CropBox(0, 0, traj.source_width, traj.source_height, BLURPAD_MODE)
    thirds = clip_duration / 3.0
    return (
        RenderSegment(0.0, thirds, box),
        RenderSegment(thirds, 2 * thirds, box),
        RenderSegment(2 * thirds, clip_duration, box),
    )


def _ok_render(written: list):
    def _fn(src, start, end, box, out, w, h, bitrate):
        Path(out).write_bytes(b"\x00")
        written.append((box, Path(out)))

    return _fn


def _ok_video_render(written: list):
    def _fn(src, start, end, box, out, w, h, bitrate):
        Path(out).write_bytes(b"\x00")
        written.append((src, start, end, box, Path(out)))

    return _fn


def _ok_concat_mux(written: list):
    def _fn(parts, src, start, end, out):
        Path(out).write_bytes(b"\x00")
        written.append((list(parts), src, start, end, Path(out)))

    return _fn


def _serial_map(fn, items):
    """Serial stand-in for the bounded thread pool — deterministic, no threads."""
    return [fn(i) for i in items]


def _render(clips, out_dir, **kw):
    written = kw.pop("written", [])
    selector = kw.pop("selector", _FakeSelector(_track_traj()))
    return render_vertical_clips(
        clips,
        "/abs/path/source.mp4",
        out_dir,
        kw.pop("scene_cut_times", ()),
        selector=selector,
        _segments_fn=kw.pop("segments_fn", render_mod._default_segments_fn),
        _render_fn=kw.pop("render_fn", _ok_render(written)),
        _video_render_fn=kw.pop("video_render_fn", _ok_video_render([])),
        _concat_mux_fn=kw.pop("concat_mux_fn", _ok_concat_mux([])),
        _probe_fn=kw.pop("probe_fn", lambda p: (1080, 1920)),
        _write_fn=kw.pop("write_fn", lambda p, d: None),
        _clock=lambda: "2026-06-17T00:00:00Z",
        _map_fn=kw.pop("map_fn", _serial_map),
        **kw,
    )


# ---- pure builders ----


def _blurpad_box() -> CropBox:
    return CropBox(0, 0, 1920, 1080, BLURPAD_MODE)


def test_blurpad_graph_for_returns_blurpad_filtergraph():
    graph = _blurpad_graph_for(_blurpad_box(), 1080, 1920)
    assert "split=2" in graph
    assert "force_original_aspect_ratio=decrease" in graph


def test_blurpad_graph_for_rejects_non_blurpad_box():
    # Founder mandate: speaker-crop is permanently disabled — a CROP box is a bug.
    with pytest.raises(CropModeError):
        _blurpad_graph_for(CropBox(0, 0, 608, 1080, CROP_MODE), 1080, 1920)


def test_build_blurpad_filtergraph():
    graph = _build_blurpad_filtergraph(1080, 1920)
    assert "split=2" in graph
    assert "gblur=sigma=20" in graph
    assert "force_original_aspect_ratio=decrease" in graph
    assert "overlay=(W-w)/2:(H-h)/2" in graph


def test_render_argv_uses_libopenh264_not_libx264():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _blurpad_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "libopenh264" in argv
    assert "libx264" not in argv


def test_render_argv_has_no_crf_and_no_rc_mode():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _blurpad_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "-crf" not in argv
    assert "-rc_mode" not in argv


def test_render_argv_has_lgpl_delivery_knobs_and_seek_order():
    argv = _build_render_argv("s.mp4", 3.0, 8.0, _blurpad_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert argv.index("-ss") < argv.index("-i")  # fast accurate seek
    for token in (
        "-b:v",
        "6M",
        "-maxrate",
        "8M",
        "yuv420p",
        "aac",
        "+faststart",
    ):
        assert token in argv
    # The build-specific libopenh264 knob is omitted for ffmpeg portability.
    assert "-allow_skip_frames" not in argv


def test_render_argv_uses_blurpad_graph():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _blurpad_box(), Path("o.mp4"), 1080, 1920, "6M")
    graph = argv[argv.index("-vf") + 1]
    assert "split=2" in graph


# ---- orchestrator ----


def test_produces_expected_clip_count(tmp_path):
    written: list = []
    manifest = _render([_clip(0), _clip(1)], tmp_path, written=written)
    assert manifest.clip_count == 2
    assert len(list(tmp_path.glob("clip_*.mp4"))) == 2
    assert len(written) == 2


def test_clips_ranked_by_score_in_manifest(tmp_path):
    # Pass out of order; orchestrator sorts by rank and re-derives 0..n-1.
    manifest = _render([_clip(1, aggregate=70.0), _clip(0, aggregate=90.0)], tmp_path)
    ranks = [c.rank for c in manifest.clips]
    assert ranks == [0, 1]
    assert manifest.clips[0].score == 90.0
    assert manifest.clips[1].score == 70.0


def test_clip_filenames_are_rank_ordered_zero_padded(tmp_path):
    manifest = _render([_clip(0), _clip(1)], tmp_path)
    assert [c.path for c in manifest.clips] == ["clip_00.mp4", "clip_01.mp4"]


def test_clips_are_vertical_offline_probe(tmp_path):
    manifest = _render([_clip(0)], tmp_path)
    assert (manifest.clips[0].width, manifest.clips[0].height) == (1080, 1920)


def test_raises_when_probe_not_1080x1920(tmp_path):
    with pytest.raises(DimensionMismatchError):
        _render([_clip(0)], tmp_path, probe_fn=lambda p: (720, 1280))


def test_raises_on_nonpositive_span(tmp_path):
    with pytest.raises(ValueError, match="positive"):
        _render([_clip(0, start=10.0, end=10.0)], tmp_path)


def test_raises_on_over_180s_clip(tmp_path):
    with pytest.raises(ClipDurationError):
        _render([_clip(0, start=0.0, end=200.0)], tmp_path)


def test_raises_on_empty_output_file(tmp_path):
    def empty_render(src, start, end, box, out, w, h, bitrate):
        Path(out).write_bytes(b"")  # ffmpeg "succeeded" but produced nothing

    with pytest.raises(RenderOutputError):
        _render([_clip(0)], tmp_path, render_fn=empty_render)


def test_raises_on_noncontiguous_ranks(tmp_path):
    with pytest.raises(RuntimeError, match="contiguous"):
        _render([_clip(0), _clip(2)], tmp_path)


def test_empty_clips_yields_empty_manifest_and_no_render(tmp_path):
    calls = {"n": 0}

    def spy_render(*a):
        calls["n"] += 1

    manifest = _render([], tmp_path, render_fn=spy_render)
    assert manifest.clip_count == 0
    assert manifest.clips == ()
    assert calls["n"] == 0


def test_general_trajectory_uses_blurpad_box(tmp_path):
    written: list = []
    _render([_clip(0)], tmp_path, selector=_FakeSelector(_general_traj()), written=written)
    assert written[0][0].mode == BLURPAD_MODE


def test_threads_scene_cuts_to_selector(tmp_path):
    selector = _FakeSelector(_track_traj())
    _render(
        [_clip(0, start=10.0, end=55.0)],
        tmp_path,
        selector=selector,
        scene_cut_times=(5.0, 20.0, 90.0),
    )
    assert selector.calls[0] == ("/abs/path/source.mp4", 10.0, 55.0, (5.0, 20.0, 90.0))


def test_manifest_source_is_basename_not_absolute(tmp_path):
    manifest = _render([_clip(0)], tmp_path)
    assert manifest.source == "source.mp4"


def test_writes_manifest_json_payload(tmp_path):
    captured: dict = {}
    _render([_clip(0)], tmp_path, write_fn=lambda p, d: captured.update(path=p, data=d))
    assert captured["path"] == tmp_path / "manifest.json"
    assert captured["data"]["clip_count"] == 1


def test_default_selector_is_mediapipe(tmp_path, monkeypatch):
    used = {"made": False}

    class _Spy(_FakeSelector):
        def __init__(self):
            super().__init__(_general_traj())
            used["made"] = True

    monkeypatch.setattr(render_mod, "MediapipeSpeakerRegionSelector", _Spy)
    written: list = []
    render_vertical_clips(
        [_clip(0)],
        "/abs/source.mp4",
        tmp_path,
        (),
        selector=None,
        _render_fn=_ok_render(written),
        _probe_fn=lambda p: (1080, 1920),
        _write_fn=lambda p, d: None,
        _clock=lambda: "t",
    )
    assert used["made"] is True


def test_write_manifest_json_round_trips(tmp_path):
    import json

    path = tmp_path / "m.json"
    _write_manifest_json(path, {"schema_version": 2, "clips": []})
    assert json.loads(path.read_text(encoding="utf-8")) == {"schema_version": 2, "clips": []}


# ---- dynamic-reframe: video-only argv + concat builders ----


def test_video_render_argv_is_audio_free():
    argv = _build_video_render_argv(
        "s.mp4", 0.0, 5.0, _blurpad_box(), Path("o.mp4"), 1080, 1920, "6M"
    )
    assert "-an" in argv  # video-only segment
    assert "aac" not in argv and "-c:a" not in argv  # audio is cut once in the concat step
    assert "libopenh264" in argv


def test_concat_list_one_line_per_part_escaped(tmp_path):
    text = _build_concat_list([tmp_path / "a'b.mp4", tmp_path / "c.mp4"])
    lines = text.strip().split("\n")
    assert len(lines) == 2
    assert lines[0].startswith("file '") and lines[0].endswith("'")
    assert "'\\''" in lines[0]  # apostrophe escaped per concat-demuxer convention


def test_concat_mux_argv_single_audio_cut_and_maps():
    argv = _build_concat_mux_argv(Path("l.txt"), "s.mp4", 10.0, 55.0, Path("o.mp4"))
    for tok in ("-f", "concat", "-safe", "0", "0:v:0", "1:a:0", "-c:a", "aac", "-shortest"):
        assert tok in argv
    assert argv[argv.index("-ss") + 1] == "10.0"  # audio window seek
    assert argv[argv.index("-t") + 1] == "45.0"  # audio window span = end - start
    assert argv[argv.index("-c:v") + 1] == "copy"  # video parts copied, never re-encoded


def test_write_concat_list_round_trips():
    path = _write_concat_list("file 'x.mp4'\n")
    try:
        assert path.read_text(encoding="utf-8") == "file 'x.mp4'\n"
    finally:
        path.unlink()


# ---- dynamic-reframe: multi-segment orchestration ----


def test_multi_segment_renders_parts_then_concats(tmp_path):
    vid: list = []
    mux: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_general_traj_for_segments()),
        segments_fn=_three_blurpad_segments_fn,
        video_render_fn=_ok_video_render(vid),
        concat_mux_fn=_ok_concat_mux(mux),
    )
    assert len(vid) == 3  # one video-only render per segment
    assert len(mux) == 1  # single concat-mux
    parts, src, start, end, _out = mux[0]
    assert len(parts) == 3 and src == "/abs/path/source.mp4"
    assert (start, end) == (10.0, 55.0)  # ONE clip-wide audio cut window
    assert [round(v[1], 2) for v in vid] == [10.0, 25.0, 40.0]  # source-relative seg starts
    assert all(v[3].mode == BLURPAD_MODE for v in vid)  # every segment is blur-pad, never crop


def test_single_segment_uses_fast_path_not_concat(tmp_path):
    vid: list = []
    mux: list = []
    rendered: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_track_traj()),
        written=rendered,
        video_render_fn=_ok_video_render(vid),
        concat_mux_fn=_ok_concat_mux(mux),
    )
    assert len(rendered) == 1 and vid == [] and mux == []  # fast path, no segment seams


def test_multi_segment_empty_part_raises_before_concat(tmp_path):
    def empty_video(src, start, end, box, out, w, h, bitrate):
        Path(out).write_bytes(b"")

    mux: list = []
    with pytest.raises(RenderOutputError):
        _render(
            [_clip(0)],
            tmp_path,
            selector=_FakeSelector(_general_traj_for_segments()),
            segments_fn=_three_blurpad_segments_fn,
            video_render_fn=empty_video,
            concat_mux_fn=_ok_concat_mux(mux),
        )
    assert mux == []  # never reached the concat step


def test_multi_segment_part_dim_mismatch_raises(tmp_path):
    with pytest.raises(DimensionMismatchError):
        _render(
            [_clip(0)],
            tmp_path,
            selector=_FakeSelector(_general_traj_for_segments()),
            segments_fn=_three_blurpad_segments_fn,
            probe_fn=lambda p: (720, 1280),
        )


def test_manifest_records_segment_count_for_multi(tmp_path):
    manifest = _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_general_traj_for_segments()),
        segments_fn=_three_blurpad_segments_fn,
    )
    assert manifest.clips[0].segment_count == 3


def test_manifest_segment_count_is_one_on_fast_path(tmp_path):
    manifest = _render([_clip(0)], tmp_path)  # default single full-frame blur-pad segment
    assert manifest.clips[0].segment_count == 1


def test_live_segments_fn_never_crops_even_on_track_trajectory(tmp_path):
    # Founder mandate: a face-track trajectory must STILL render full-frame blur-pad.
    written: list = []
    _render([_clip(0)], tmp_path, selector=_FakeSelector(_track_traj()), written=written)
    assert written[0][0].mode == BLURPAD_MODE


def test_default_segments_fn_yields_single_blurpad_segment():
    segs = render_mod._default_segments_fn(_track_traj(), 45.0)
    assert len(segs) == 1
    assert segs[0].box.mode == BLURPAD_MODE


def test_caption_band_seam_default_off_records_none(tmp_path):
    manifest = _render([_clip(0)], tmp_path)  # default _no_caption_band
    assert manifest.clips[0].caption_band is None


def test_caption_band_seam_records_detected_band(tmp_path):
    from fliphouse_worker.clipping.caption_band import CaptionBand

    manifest = _render(
        [_clip(0)],
        tmp_path,
        _caption_band_fn=lambda src, start, end: CaptionBand(900, 940, 0.7),
    )
    assert manifest.clips[0].caption_band == {"y_top": 900, "y_bottom": 940, "confidence": 0.7}


# ---- atomic-rename + timeout hardening (P2-2.5 step 5) ----


def test_timeout_for_clamps_floor_and_scales():
    assert _timeout_for(1.0) == render_mod.MIN_RENDER_TIMEOUT_S  # floor wins for a tiny clip
    assert _timeout_for(60.0) == 60.0 * render_mod.RENDER_REALTIME_FACTOR  # scales above the floor


def test_render_writes_partial_then_replaces(tmp_path):
    seen_render_path = {}
    replaced = []

    def render_fn(src, start, end, box, out, w, h, bitrate):
        seen_render_path["out"] = Path(out)
        Path(out).write_bytes(b"\x00")

    def replace_fn(src, dst):
        replaced.append((Path(src), Path(dst)))
        Path(src).replace(dst)

    _render(
        [_clip(0)],
        tmp_path,
        render_fn=render_fn,
        _replace_fn=replace_fn,
    )
    # ffmpeg wrote to a *.partial; the verified file was atomically promoted.
    assert seen_render_path["out"].name == "clip_00.mp4.partial"
    assert replaced == [(tmp_path / "clip_00.mp4.partial", tmp_path / "clip_00.mp4")]
    assert (tmp_path / "clip_00.mp4").exists()
    assert not (tmp_path / "clip_00.mp4.partial").exists()


def test_render_does_not_replace_when_probe_fails(tmp_path):
    replaced = []
    with pytest.raises(DimensionMismatchError):
        _render(
            [_clip(0)],
            tmp_path,
            probe_fn=lambda p: (720, 1280),  # wrong dims → fail-closed before promote
            _replace_fn=lambda s, d: replaced.append((s, d)),
        )
    assert replaced == []  # never promoted a bad clip
    assert not (tmp_path / "clip_00.mp4").exists()
