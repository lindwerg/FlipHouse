"""Codec / pixel-format / audio assertions (checkpoint-C contract extension).

Platforms (TikTok/YouTube/IG) reject non-H.264 or exotic pixel formats, and a
silent clip is a broken result. These assertions catch both deterministically;
they also back the P3 DoD `test_final_is_1080x1920_h264`.
"""

from collections.abc import Callable
from pathlib import Path

from fliphouse_worker.video_asserts import (
    has_audio,
    probe_pixel_format,
    probe_video_codec,
)


def test_probe_video_codec_is_h264(make_test_clip: Callable[[], Path]):
    assert probe_video_codec(make_test_clip()) == "h264"


def test_probe_pixel_format_is_yuv420p(make_test_clip: Callable[[], Path]):
    assert probe_pixel_format(make_test_clip()) == "yuv420p"


def test_has_audio_true_when_audio_stream_present(make_lavfi_clip: Callable[..., Path]):
    clip = make_lavfi_clip("testsrc=size=1080x1920:rate=24:duration=1", audio=True)
    assert has_audio(clip) is True


def test_has_audio_false_for_video_only_clip(make_test_clip: Callable[[], Path]):
    assert has_audio(make_test_clip()) is False
