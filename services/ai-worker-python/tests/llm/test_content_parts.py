"""Tests for multimodal content-part builders (P2-S4).

Pure functions that produce OpenRouter wire dicts for a user message — text and
a short base64 video clip. Raw bytes in, data-URL out; fail-closed on bad MIME
or oversize. No network.
"""

import base64

import pytest

from fliphouse_worker.llm.content_parts import (
    MAX_INLINE_VIDEO_BYTES,
    text_part,
    video_part,
)


def test_text_part_exact_shape():
    assert text_part("hi") == {"type": "text", "text": "hi"}


def test_video_part_default_mime_and_data_url():
    raw = b"\x00\x01video-bytes"
    b64 = base64.b64encode(raw).decode()
    assert video_part(raw) == {
        "type": "video_url",
        "video_url": {"url": f"data:video/mp4;base64,{b64}"},
    }


def test_video_part_explicit_webm_mime():
    part = video_part(b"abc", mime="video/webm")
    assert part["video_url"]["url"].startswith("data:video/webm;base64,")


def test_video_part_rejects_unsupported_mime():
    with pytest.raises(ValueError, match="unsupported video mime"):
        video_part(b"abc", mime="video/avi")


def test_video_part_oversize_rejected_at_cap_accepted():
    # boundary is inclusive: reject is strictly greater than the cap.
    over = b"x" * (MAX_INLINE_VIDEO_BYTES + 1)
    with pytest.raises(ValueError, match="exceeds inline cap"):
        video_part(over)
    at_cap = b"x" * MAX_INLINE_VIDEO_BYTES
    assert video_part(at_cap)["type"] == "video_url"
