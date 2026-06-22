"""GOLDEN argv test for the caption burn-in ffmpeg call (LGPL + subtitles=)."""

from __future__ import annotations

from pathlib import Path

import pytest

from fliphouse_worker.captioning.burn import (
    _build_caption_burn_argv,
    _escape_subtitles_path,
)


def _argv(src: str = "in.mp4", ass: str = "/w/cap.ass", out: str = "/w/out.mp4") -> list[str]:
    return _build_caption_burn_argv(src, Path(ass), Path(out), 1080, 1920)


def test_argv_uses_lgpl_libopenh264_never_libx264() -> None:
    argv = _argv()
    assert "libopenh264" in argv
    assert "libx264" not in argv
    # The LGPL invariant: no GPL encoder may sneak in.
    assert "-c:v" in argv and argv[argv.index("-c:v") + 1] == "libopenh264"


def test_argv_copies_audio_and_burns_via_subtitles_filter() -> None:
    argv = _argv(ass="/w/cap.ass")
    # Audio is copied (clip already cut to t=0 with correct audio) — never re-encoded.
    assert argv[argv.index("-c:a") + 1] == "copy"
    vf = argv[argv.index("-vf") + 1]
    assert vf.startswith("subtitles=")
    assert "cap.ass" in vf


def test_argv_has_no_seek_or_trim_flags() -> None:
    # The clip is ALREADY cut to t=0 — a stray -ss/-t would re-cut and desync captions.
    argv = _argv()
    assert "-ss" not in argv
    assert "-t" not in argv


def test_argv_emits_faststart_and_yuv420p() -> None:
    argv = _argv()
    assert argv[argv.index("-movflags") + 1] == "+faststart"
    assert argv[argv.index("-pix_fmt") + 1] == "yuv420p"


def test_argv_input_and_output_are_the_given_paths() -> None:
    argv = _build_caption_burn_argv("src.mp4", Path("/w/c.ass"), Path("/w/o.mp4"), 1080, 1920)
    assert argv[argv.index("-i") + 1] == "src.mp4"
    assert argv[-1] == "/w/o.mp4"


def test_subtitles_path_escapes_the_drive_colon_and_backslashes() -> None:
    # A ':' inside the subtitles= value separates filter options — must be escaped,
    # or libass reads the path tail as bogus filter args. Backslashes are doubled.
    escaped = _escape_subtitles_path(Path("/w/sub:dir/cap.ass"))
    assert "\\:" in escaped
    assert ":" not in escaped.replace("\\:", "")


def test_subtitles_filter_value_is_wrapped_and_escaped() -> None:
    argv = _build_caption_burn_argv(
        "in.mp4", Path("/tmp/a:b/cap.ass"), Path("/w/o.mp4"), 1080, 1920
    )
    vf = argv[argv.index("-vf") + 1]
    # The escaped colon survives into the assembled filtergraph.
    assert "\\:" in vf


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
