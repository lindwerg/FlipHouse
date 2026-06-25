"""render — pure argv/filtergraph builders + the orchestrator with every seam faked."""

from pathlib import Path

import pytest

from fliphouse_worker.clipping import render as render_mod
from fliphouse_worker.clipping.crop_geometry import (
    BLURPAD_MODE,
    CONTAIN_LAYOUT,
    CROP_MODE,
    GENERAL_MARK,
    STACK_LAYOUT,
    TRACK_MARK,
    CropBox,
    CropKeyframe,
    CropTrajectory,
)
from fliphouse_worker.clipping.render import (
    CONTAIN_BLUR_SIGMA,
    CONTAIN_DARKEN,
    ClipDurationError,
    CropModeError,
    DimensionMismatchError,
    RenderOutputError,
    _build_concat_list,
    _build_concat_mux_argv,
    _build_contain_filtergraph,
    _build_crop_filtergraph,
    _build_render_argv,
    _build_stack_filtergraph,
    _build_video_render_argv,
    _crop_graph_for,
    _cropdetect_result,
    _escape_subtitles_path,
    _parse_cropdetect,
    _resolve_contain_box,
    _resolve_contain_segments,
    _timeout_for,
    _video_filter_args,
    _write_caption_ass,
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


def _multi_traj() -> CropTrajectory:
    """A TRACK→GENERAL→TRACK trajectory → three fill-crop render segments.

    The non-causal mode timeline votes per scene-cut block, so the three runs only
    materialise when a cut delimits each transition. ``_MULTI_CUTS`` (absolute, clip starts
    at 10.0) supplies cuts at clip-relative 2.75 / 4.25 — between the TRACK/GENERAL/TRACK
    blocks. Without them the whole clip is one block (one segment).
    """
    return CropTrajectory(
        keyframes=tuple(
            [CropKeyframe(i * 0.5, 960.0, TRACK_MARK) for i in range(6)]
            + [CropKeyframe((6 + i) * 0.5, None, GENERAL_MARK) for i in range(3)]
            + [CropKeyframe((9 + i) * 0.5, 500.0, TRACK_MARK) for i in range(3)]
        ),
        source_width=1920,
        source_height=1080,
    )


# Absolute scene cuts (clip starts at 10.0) that split _multi_traj into its three blocks:
# clip-relative 2.75 (TRACK→GENERAL) and 4.25 (GENERAL→TRACK).
_MULTI_CUTS: tuple[float, ...] = (12.75, 14.25)


def _crop_box() -> CropBox:
    return CropBox(0, 0, 608, 1080, CROP_MODE)


def _ok_render(written: list):
    def _fn(src, start, end, box, out, w, h, bitrate, ass_path=None):
        Path(out).write_bytes(b"\x00")
        written.append((box, Path(out), ass_path))

    return _fn


def _ok_video_render(written: list):
    def _fn(src, start, end, box, out, w, h, bitrate):
        Path(out).write_bytes(b"\x00")
        written.append((src, start, end, box, Path(out)))

    return _fn


def _ok_concat_mux(written: list):
    def _fn(parts, src, start, end, out, ass_path=None):
        Path(out).write_bytes(b"\x00")
        written.append((list(parts), src, start, end, Path(out), ass_path))

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
        _render_fn=kw.pop("render_fn", _ok_render(written)),
        _video_render_fn=kw.pop("video_render_fn", _ok_video_render([])),
        _concat_mux_fn=kw.pop("concat_mux_fn", _ok_concat_mux([])),
        _probe_fn=kw.pop("probe_fn", lambda p: (1080, 1920)),
        _cropdetect_fn=kw.pop("cropdetect_fn", lambda src, start, end: None),
        _write_fn=kw.pop("write_fn", lambda p, d: None),
        _clock=lambda: "2026-06-17T00:00:00Z",
        _map_fn=kw.pop("map_fn", _serial_map),
        **kw,
    )


# ---- pure builders ----


def test_build_crop_filtergraph():
    box = CropBox(x=100, y=0, w=608, h=1080, mode=CROP_MODE)
    assert (
        _build_crop_filtergraph(box, 1080, 1920) == "crop=608:1080:100:0,scale=1080:1920,setsar=1"
    )


def test_crop_graph_for_returns_crop_filtergraph():
    graph = _crop_graph_for(_crop_box(), 1080, 1920)
    assert graph.startswith("crop=608:1080:0:0")
    assert "scale=1080:1920" in graph and "setsar=1" in graph


def test_crop_graph_for_rejects_blurpad_box():
    # Founder mandate: blur-pad is permanently disabled — a BLURPAD box is a bug.
    with pytest.raises(CropModeError):
        _crop_graph_for(CropBox(0, 0, 1920, 1080, BLURPAD_MODE), 1080, 1920)


def test_blurpad_filtergraph_is_removed_from_module():
    # No live path can blur-pad: the blur-pad filtergraph builder must not exist.
    assert not hasattr(render_mod, "_build_blurpad_filtergraph")


def test_render_argv_uses_libopenh264_not_libx264():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "libopenh264" in argv
    assert "libx264" not in argv


def test_render_argv_has_no_crf_and_no_rc_mode():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "-crf" not in argv
    assert "-rc_mode" not in argv


def test_render_argv_has_lgpl_delivery_knobs_and_seek_order():
    argv = _build_render_argv("s.mp4", 3.0, 8.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
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


def test_render_argv_uses_crop_graph():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
    graph = argv[argv.index("-vf") + 1]
    assert graph.startswith("crop=") and "split=2" not in graph  # fill-crop, never blur-pad


# ---- split-screen STACK render ----


def _stack_box() -> CropBox:
    # Two per-speaker panels (each already 1080:960 — the delivery tile ratio).
    top = CropBox(x=0, y=0, w=540, h=480, mode=CROP_MODE)
    bottom = CropBox(x=1380, y=0, w=540, h=480, mode=CROP_MODE)
    return CropBox(
        x=0, y=0, w=1920, h=480, mode=CROP_MODE, layout=STACK_LAYOUT, panels=(top, bottom)
    )


def test_build_stack_filtergraph_vstacks_two_panels():
    graph = _build_stack_filtergraph(_stack_box(), 1080, 1920)
    # one crop+scale chain per panel, each scaled to the equal-height tile (1920/2 = 960)
    assert "[0:v]crop=540:480:0:0,scale=1080:960,setsar=1[s0]" in graph
    assert "[0:v]crop=540:480:1380:0,scale=1080:960,setsar=1[s1]" in graph
    # vstacked top→bottom into the named output
    assert graph.endswith("[s0][s1]vstack=inputs=2[v]")


def test_crop_graph_for_routes_stack_layout_to_vstack():
    graph = _crop_graph_for(_stack_box(), 1080, 1920)
    assert "vstack=inputs=2" in graph


def test_stack_filtergraph_fails_closed_on_too_few_panels():
    bad = CropBox(x=0, y=0, w=1920, h=480, mode=CROP_MODE, layout=STACK_LAYOUT, panels=())
    with pytest.raises(CropModeError, match="needs >=2 panels"):
        _build_stack_filtergraph(bad, 1080, 1920)


def test_stack_filtergraph_fails_closed_when_height_not_tileable():
    with pytest.raises(CropModeError, match="not evenly tileable"):
        _build_stack_filtergraph(_stack_box(), 1080, 1921)


def test_stack_render_argv_uses_filter_complex_and_maps_video_and_audio():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _stack_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "-filter_complex" in argv and "-vf" not in argv
    # the vstacked video stream is explicitly selected, and the source audio mapped
    vi = argv.index("-filter_complex")
    assert argv[vi + 2] == "-map" and argv[vi + 3] == "[v]"
    assert "0:a:0?" in argv  # optional source audio map (filter_complex breaks auto-map)
    assert "libopenh264" in argv  # still LGPL-clean


def test_stack_video_render_argv_is_audio_free_filter_complex():
    argv = _build_video_render_argv(
        "s.mp4", 0.0, 5.0, _stack_box(), Path("o.mp4"), 1080, 1920, "6M"
    )
    assert "-filter_complex" in argv and "-vf" not in argv
    assert "-an" in argv  # video-only segment render
    assert "0:a:0?" not in argv  # no audio map on a -an render


def test_single_layout_render_argv_keeps_plain_vf_and_no_audio_map():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "-vf" in argv and "-filter_complex" not in argv
    assert "0:a:0?" not in argv  # single-crop auto-maps audio, no explicit map


# ---- full-frame CONTAIN (b-roll blurred-margin fill) render ----


def _contain_box() -> CropBox:
    # The whole 1920x1080 source frame, CONTAIN layout (b-roll, nothing cropped out).
    return CropBox(x=0, y=0, w=1920, h=1080, mode=CROP_MODE, layout=CONTAIN_LAYOUT)


def test_build_contain_filtergraph_emits_exact_split_overlay_graph():
    # EXACT graph (research-validated): LEAD crop (strip baked bars on the detected region)
    # → split → bg cover-zoom+blur+darken, fg contain, overlay centred, setsar=1 AFTER the
    # overlay (square pixels), named [v] output. For the whole-frame box the lead crop is a
    # no-op (crop=1920:1080:0:0) so behaviour matches the bar-free case exactly.
    graph = _build_contain_filtergraph(_contain_box(), 1080, 1920)
    assert graph == (
        "[0:v]crop=1920:1080:0:0,split=2[bg][fg];"
        "[bg]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920,gblur=sigma={CONTAIN_BLUR_SIGMA},eq=brightness={CONTAIN_DARKEN}[bg2];"
        "[fg]scale=1080:1920:force_original_aspect_ratio=decrease[fg2];"
        "[bg2][fg2]overlay=(W-w)/2:(H-h)/2,setsar=1[v]"
    )
    # The anti-stretch invariant: setsar=1 lands AFTER overlay, not on the fg leg.
    assert graph.endswith("overlay=(W-w)/2:(H-h)/2,setsar=1[v]")
    assert ",setsar=1[fg2]" not in graph


def test_build_contain_filtergraph_leads_with_crop_on_stripped_region():
    # A bar-stripped CONTAIN box (a 600-wide pillarboxed content region) → the graph LEADS
    # with crop=600:1080:660:0 so the baked side bars are removed before the contain/overlay.
    box = CropBox(x=660, y=0, w=600, h=1080, mode=CROP_MODE, layout=CONTAIN_LAYOUT)
    graph = _build_contain_filtergraph(box, 1080, 1920)
    assert graph.startswith("[0:v]crop=600:1080:660:0,split=2[bg][fg];")
    assert graph.endswith("overlay=(W-w)/2:(H-h)/2,setsar=1[v]")


def test_crop_graph_for_routes_contain_layout_to_split_overlay():
    graph = _crop_graph_for(_contain_box(), 1080, 1920)
    assert graph.startswith("[0:v]crop=1920:1080:0:0,split=2[bg][fg]")
    assert "gblur=sigma=" in graph and "overlay=" in graph


def test_contain_render_argv_uses_filter_complex_maps_video_and_audio():
    argv = _build_render_argv("s.mp4", 0.0, 5.0, _contain_box(), Path("o.mp4"), 1080, 1920, "6M")
    assert "-filter_complex" in argv and "-vf" not in argv
    vi = argv.index("-filter_complex")
    assert argv[vi + 2] == "-map" and argv[vi + 3] == "[v]"
    assert "0:a:0?" in argv  # filter_complex breaks audio auto-map → explicit source map
    assert "libopenh264" in argv  # still LGPL-clean


def test_contain_video_render_argv_is_audio_free_filter_complex():
    argv = _build_video_render_argv(
        "s.mp4", 0.0, 5.0, _contain_box(), Path("o.mp4"), 1080, 1920, "6M"
    )
    assert "-filter_complex" in argv and "-vf" not in argv
    assert "-an" in argv  # video-only segment render
    assert "0:a:0?" not in argv  # no audio map on a -an render


# ---- content-aware b-roll: cropdetect parse + region resolve ----


def test_parse_cropdetect_last_crop_line_wins():
    # cropdetect ACCUMULATES across the window; the LAST crop= is its settled estimate.
    stderr = (
        "[Parsed_cropdetect_0 @ 0x1] x1:0 x2:1919 crop=1600:1080:160:0\n"
        "[Parsed_cropdetect_0 @ 0x1] x1:0 x2:1919 crop=608:1080:656:0\n"
    )
    assert _parse_cropdetect(stderr) == (656, 0, 608, 1080)  # (x, y, w, h) of the LAST line


def test_parse_cropdetect_pillarbox_yields_narrower_width():
    # A 16:9 frame with a vertical content column → cropdetect reports a NARROW width.
    stderr = "x1 x2 crop=608:1080:656:0\n"
    x, y, w, h = _parse_cropdetect(stderr)
    assert (x, y, w, h) == (656, 0, 608, 1080) and w < 1920


def test_parse_cropdetect_letterbox_yields_shorter_height():
    # A frame with top/bottom bars → cropdetect reports a SHORTER height.
    stderr = "crop=1920:608:0:236\n"
    x, y, w, h = _parse_cropdetect(stderr)
    assert (x, y, w, h) == (0, 236, 1920, 608) and h < 1080


def test_parse_cropdetect_malformed_is_none():
    assert _parse_cropdetect("no crop here at all") is None
    assert _parse_cropdetect("") is None


def test_cropdetect_result_nonzero_rc_is_none():
    # A NON-ZERO ffmpeg exit is INCONCLUSIVE: even a stale/partial crop= line in stderr
    # must NOT be trusted → fail-OPEN to None (whole-frame CONTAIN), same as any failure.
    stderr = "x1 x2 crop=608:1080:656:0\n"  # a plausible crop= line that must be ignored
    assert _cropdetect_result(1, stderr) is None
    assert _cropdetect_result(255, stderr) is None


def test_cropdetect_result_zero_rc_parses_region():
    # rc==0 → parse the settled estimate via _parse_cropdetect (last crop= line wins).
    stderr = "x1 x2 crop=608:1080:656:0\n"
    assert _cropdetect_result(0, stderr) == (656, 0, 608, 1080)


def test_cropdetect_result_zero_rc_parse_miss_is_none():
    # rc==0 but no parsable crop= line → None (fail-OPEN), inherited from _parse_cropdetect.
    assert _cropdetect_result(0, "no crop here at all") is None


def test_resolve_contain_box_none_keeps_whole_frame():
    # Inconclusive detection → fail-OPEN to the original whole-frame CONTAIN box exactly.
    whole = _contain_box()
    assert _resolve_contain_box(whole, 1920, 1080, None) is whole


def test_resolve_contain_box_portrait_region_becomes_single_fill():
    # A detected vertical content region → a SINGLE 9:16 FILL box (flows through -vf).
    box = _resolve_contain_box(_contain_box(), 1920, 1080, (660, 0, 600, 1080))
    assert box.mode == CROP_MODE and box.layout != CONTAIN_LAYOUT
    assert box.layout == "SINGLE"


def test_resolve_contain_box_landscape_region_stays_contain_stripped():
    # A detected landscape region (bar-stripped) stays CONTAIN, but on the region, not frame.
    box = _resolve_contain_box(_contain_box(), 1920, 1080, (0, 236, 1920, 608))
    assert box.layout == CONTAIN_LAYOUT
    assert (box.x, box.y, box.w, box.h) == (0, 236, 1920, 608)


def test_resolve_contain_box_fails_open_on_bad_region():
    # A region escaping the source must NOT raise (a paid b-roll segment) → whole-frame box.
    whole = _contain_box()
    assert _resolve_contain_box(whole, 1920, 1080, (1900, 0, 400, 1080)) is whole


def test_resolve_contain_segments_only_touches_contain_segments():
    track = RenderSegment(0.0, 2.0, _crop_box())  # SINGLE speaker crop — passed through
    contain = RenderSegment(2.0, 4.0, _contain_box())  # CONTAIN — refined

    def fake_detect(src, start, end):
        # absolute window = clip_start(10.0) + seg-relative
        assert (start, end) == (12.0, 14.0)  # only the CONTAIN segment is probed
        return (660, 0, 600, 1080)  # vertical content → FILL

    out = _resolve_contain_segments([track, contain], "s.mp4", 10.0, 1920, 1080, fake_detect)
    assert out[0].box is track.box  # speaker crop byte-identical (TRACK path untouched)
    assert out[0] == track
    assert out[1].box.layout == "SINGLE"  # CONTAIN refined to a FILL box
    assert (out[1].start_s, out[1].end_s) == (2.0, 4.0)


def test_resolve_contain_segments_inconclusive_keeps_whole_frame_contain():
    contain = RenderSegment(0.0, 2.0, _contain_box())
    out = _resolve_contain_segments([contain], "s.mp4", 0.0, 1920, 1080, lambda s, a, b: None)
    assert out[0].box.layout == CONTAIN_LAYOUT
    assert (out[0].box.x, out[0].box.y, out[0].box.w, out[0].box.h) == (0, 0, 1920, 1080)


# ---- content-aware b-roll: orchestrator end-to-end ----


def test_general_clip_vertical_content_fills_frame_not_blurpad(tmp_path):
    # A b-roll clip whose content is vertical (cropdetect finds a narrow column) FILLs the
    # 9:16 frame (SINGLE -vf crop+scale+setsar), NOT a blur-pad CONTAIN.
    written: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_general_traj()),
        written=written,
        cropdetect_fn=lambda src, start, end: (660, 0, 600, 1080),
    )
    box = written[0][0]
    assert box.mode == CROP_MODE and box.layout == "SINGLE"
    graph = _build_crop_filtergraph(box, 1080, 1920)
    assert graph == f"crop={box.w}:{box.h}:{box.x}:{box.y},scale=1080:1920,setsar=1"


def test_general_clip_landscape_content_stays_contain(tmp_path):
    # A b-roll clip with landscape content (letterbox bars stripped) stays CONTAIN, on the
    # stripped region — blur-pad look preserved.
    written: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_general_traj()),
        written=written,
        cropdetect_fn=lambda src, start, end: (0, 236, 1920, 608),
    )
    box = written[0][0]
    assert box.layout == CONTAIN_LAYOUT
    assert (box.x, box.y, box.w, box.h) == (0, 236, 1920, 608)


def test_general_clip_inconclusive_detection_is_whole_frame_contain(tmp_path):
    # Fail-OPEN: cropdetect returns None → today's exact whole-frame CONTAIN box (regression).
    written: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_general_traj()),
        written=written,
        cropdetect_fn=lambda src, start, end: None,
    )
    box = written[0][0]
    assert box.layout == CONTAIN_LAYOUT
    assert (box.x, box.y, box.w, box.h) == (0, 0, 1920, 1080)


def test_speaker_clip_never_runs_cropdetect(tmp_path):
    # The TRACK speaker-crop path must be untouched — cropdetect is gated to CONTAIN only.
    calls = {"n": 0}

    def spy_detect(src, start, end):
        calls["n"] += 1
        return None

    written: list = []
    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_track_traj()),
        written=written,
        cropdetect_fn=spy_detect,
    )
    assert calls["n"] == 0  # no cropdetect on a speaker crop
    assert written[0][0].w == 608  # the speaker column is byte-identical


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
    def empty_render(src, start, end, box, out, w, h, bitrate, ass_path=None):
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


def test_speaker_trajectory_tracks_with_a_crop_box(tmp_path):
    # SPEAKER PRESENT → a fill-crop column that FOLLOWS the speaker (never blur-pad).
    written: list = []
    _render([_clip(0)], tmp_path, selector=_FakeSelector(_track_traj()), written=written)
    box = written[0][0]
    assert box.mode == CROP_MODE
    assert box.w == 608  # a 9:16 column of a 1920x1080 source


def test_general_trajectory_uses_full_frame_contain_box_not_blurpad(tmp_path):
    # NO speaker → b-roll CONTAIN: the WHOLE source frame stays in (founder: "чтобы всё
    # входило"), filled with a blurred margin — CROP_MODE, never a BLURPAD segment.
    written: list = []
    _render([_clip(0)], tmp_path, selector=_FakeSelector(_general_traj()), written=written)
    box = written[0][0]
    assert box.mode == CROP_MODE  # never BLURPAD
    assert box.layout == CONTAIN_LAYOUT
    assert (box.x, box.y, box.w, box.h) == (0, 0, 1920, 1080)  # whole frame, nothing cropped out


def test_live_path_never_emits_a_blurpad_box(tmp_path):
    # Guard: across speaker / b-roll / multi-segment, NO box reaches render as BLURPAD.
    for traj in (_track_traj(), _general_traj(), _multi_traj()):
        written: list = []
        vid: list = []
        _render(
            [_clip(0)],
            tmp_path,
            selector=_FakeSelector(traj),
            written=written,
            video_render_fn=_ok_video_render(vid),
        )
        for box, _out, _ass in written:
            assert box.mode == CROP_MODE
        for entry in vid:
            assert entry[3].mode == CROP_MODE


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


def test_default_selector_comes_from_env_factory(tmp_path, monkeypatch):
    # render defaults the selector via the env-driven factory (GPU-ASD when enabled,
    # else CPU heuristic). Patch the factory to assert render calls it when none given.
    used = {"made": False}

    def _factory():
        used["made"] = True
        return _FakeSelector(_general_traj())

    monkeypatch.setattr(render_mod, "build_speaker_region_selector", _factory)
    written: list = []
    render_vertical_clips(
        [_clip(0)],
        "/abs/source.mp4",
        tmp_path,
        (),
        selector=None,
        _render_fn=_ok_render(written),
        _probe_fn=lambda p: (1080, 1920),
        _cropdetect_fn=lambda src, start, end: None,
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
    argv = _build_video_render_argv("s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M")
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
        selector=_FakeSelector(_multi_traj()),
        scene_cut_times=_MULTI_CUTS,
        video_render_fn=_ok_video_render(vid),
        concat_mux_fn=_ok_concat_mux(mux),
    )
    assert len(vid) == 3  # one video-only render per segment
    assert len(mux) == 1  # single concat-mux
    parts, src, start, end, _out, _ass = mux[0]
    assert len(parts) == 3 and src == "/abs/path/source.mp4"
    assert (start, end) == (10.0, 55.0)  # ONE clip-wide audio cut window
    # source-relative seg starts: boundaries snap to the block-delimiting cuts (12.75, 14.25)
    assert [round(v[1], 2) for v in vid] == [10.0, 12.75, 14.25]
    assert all(v[3].mode == CROP_MODE for v in vid)  # every segment is a fill-crop, never blur-pad


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
            selector=_FakeSelector(_multi_traj()),
            scene_cut_times=_MULTI_CUTS,
            video_render_fn=empty_video,
            concat_mux_fn=_ok_concat_mux(mux),
        )
    assert mux == []  # never reached the concat step


def test_multi_segment_part_dim_mismatch_raises(tmp_path):
    with pytest.raises(DimensionMismatchError):
        _render(
            [_clip(0)],
            tmp_path,
            selector=_FakeSelector(_multi_traj()),
            scene_cut_times=_MULTI_CUTS,
            probe_fn=lambda p: (720, 1280),
        )


def test_manifest_records_segment_count_for_multi(tmp_path):
    manifest = _render(
        [_clip(0)], tmp_path, selector=_FakeSelector(_multi_traj()), scene_cut_times=_MULTI_CUTS
    )
    assert manifest.clips[0].segment_count == 3


def test_manifest_segment_count_is_one_on_fast_path(tmp_path):
    manifest = _render([_clip(0)], tmp_path)  # default single-keyframe track trajectory
    assert manifest.clips[0].segment_count == 1


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

    def render_fn(src, start, end, box, out, w, h, bitrate, ass_path=None):
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


# ---- SPD-1: single-pass caption fold (reframe encode burns the .ass) ----


def test_escape_subtitles_path_escapes_backslash_then_colon():
    # Backslash doubled FIRST so the colon-escaping backslashes aren't re-doubled.
    assert _escape_subtitles_path(Path("/w/c.ass")) == "/w/c.ass"
    assert _escape_subtitles_path(Path("C:\\w\\c.ass")) == "C\\:\\\\w\\\\c.ass"


def test_video_filter_args_appends_subtitles_on_plain_vf_crop():
    args = _video_filter_args(_crop_box(), 1080, 1920, Path("/w/c.ass"))
    assert args[0] == "-vf"
    # subtitles= is the LAST link so captions rasterize on the final composited frame.
    assert args[1].endswith(",subtitles=/w/c.ass")
    assert args[1].startswith("crop=")


def test_video_filter_args_pipes_subtitles_after_filter_complex_v():
    args = _video_filter_args(_stack_box(), 1080, 1920, Path("/w/c.ass"))
    assert args[0] == "-filter_complex"
    # the [v] output is piped into a trailing subtitles link → [vout], which is mapped.
    assert args[1].endswith(";[v]subtitles=/w/c.ass[vout]")
    assert args[-2:] == ["-map", "[vout]"]


def test_video_filter_args_no_subtitles_when_ass_none_is_unchanged():
    # Back-compat: ass_path None reproduces the pre-SPD-1 argv exactly.
    assert _video_filter_args(_crop_box(), 1080, 1920) == _video_filter_args(
        _crop_box(), 1080, 1920, None
    )
    assert _video_filter_args(_stack_box(), 1080, 1920, None)[-1] == "[v]"


def test_render_argv_folds_subtitles_into_the_single_libopenh264_pass():
    argv = _build_render_argv(
        "s.mp4", 0.0, 5.0, _crop_box(), Path("o.mp4"), 1080, 1920, "6M", Path("/w/c.ass")
    )
    assert argv[argv.index("-c:v") + 1] == "libopenh264"  # LGPL delivery invariant holds
    assert "libx264" not in argv
    vf = argv[argv.index("-vf") + 1]
    assert vf.endswith(",subtitles=/w/c.ass")


def test_concat_mux_argv_burns_subtitles_with_libopenh264_when_ass_given():
    argv = _build_concat_mux_argv(
        Path("/w/l.txt"), "s.mp4", 0.0, 5.0, Path("o.mp4"), Path("/w/c.ass"), "6M"
    )
    # Multi-segment fold: the concat pass re-encodes ONCE with captions (no -c:v copy).
    assert argv[argv.index("-c:v") + 1] == "libopenh264"
    assert "copy" not in argv
    assert argv[argv.index("-vf") + 1] == "subtitles=/w/c.ass"


def test_concat_mux_argv_copies_video_when_no_ass():
    argv = _build_concat_mux_argv(Path("/w/l.txt"), "s.mp4", 0.0, 5.0, Path("o.mp4"))
    assert argv[argv.index("-c:v") + 1] == "copy"
    assert "subtitles=" not in " ".join(argv)


def test_write_caption_ass_writes_and_returns_path(tmp_path):
    path = _write_caption_ass("[Script Info]\n")
    try:
        assert path.suffix == ".ass"
        assert path.read_text(encoding="utf-8") == "[Script Info]\n"
    finally:
        path.unlink(missing_ok=True)


def test_render_threads_ass_to_fast_path_and_cleans_up_temp(tmp_path):
    written: list = []
    seen_ass = {}

    def _ass_for(start, end, band):
        return "[Script Info]\n"

    def render_fn(src, start, end, box, out, w, h, bitrate, ass_path=None):
        # the renderer built a real temp .ass and handed its path to the encode
        seen_ass["path"] = ass_path
        seen_ass["exists_during_encode"] = ass_path is not None and ass_path.exists()
        Path(out).write_bytes(b"\x00")
        written.append((box, Path(out), ass_path))

    _render([_clip(0)], tmp_path, render_fn=render_fn, _caption_ass_fn=_ass_for)
    assert seen_ass["path"] is not None
    assert seen_ass["exists_during_encode"] is True
    # the temp .ass is swept after the encode (no leak)
    assert not seen_ass["path"].exists()


def test_render_burns_ass_in_concat_for_multi_segment(tmp_path):
    mux: list = []

    def _ass_for(start, end, band):
        return "[Script Info]\n"

    def concat_mux_fn(parts, src, start, end, out, ass_path=None):
        mux.append(ass_path)
        Path(out).write_bytes(b"\x00")

    _render(
        [_clip(0)],
        tmp_path,
        selector=_FakeSelector(_multi_traj()),
        scene_cut_times=_MULTI_CUTS,
        video_render_fn=_ok_video_render([]),
        concat_mux_fn=concat_mux_fn,
        _caption_ass_fn=_ass_for,
    )
    assert len(mux) == 1 and mux[0] is not None  # the clip-wide .ass reached the concat
    assert not mux[0].exists()  # swept after the concat encode


def test_render_no_ass_when_caption_fn_yields_none(tmp_path):
    written: list = []

    def render_fn(src, start, end, box, out, w, h, bitrate, ass_path=None):
        Path(out).write_bytes(b"\x00")
        written.append(ass_path)

    # default _no_caption_ass yields None → uncaptioned clip, no temp .ass built
    _render([_clip(0)], tmp_path, render_fn=render_fn)
    assert written == [None]
