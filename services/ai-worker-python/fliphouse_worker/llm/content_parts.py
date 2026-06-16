"""Multimodal user-message content-part builders (P2-S4).

Pure functions that produce OpenRouter wire dicts for a user message: plain text
and a short base64-inlined video clip. A transport concern (it emits the exact
OpenAI/OpenRouter content shape), so it lives in llm/ beside the adapter.

Raw bytes in → base64 data-URL out; the size guard runs on the TRUE payload, and
the provider-specific video shape is quarantined in one function (one-line fix if
the June-2026 form differs). Only short pre-cut clips are inlined — never the
whole source (doc 04 §2, founder re-plan).
"""

from __future__ import annotations

import base64
from typing import Any

DEFAULT_VIDEO_MIME = "video/mp4"
# Intersection of what OpenRouter forwards and Gemini decodes for inline clips.
SUPPORTED_VIDEO_MIMES = frozenset({"video/mp4", "video/webm"})
# Operational cap: base64 adds ~33% (~27 MB on the wire) — under the 100 MB hard
# limit. No File API via OpenRouter, so oversize fails fast (S6 ffmpeg re-cuts).
MAX_INLINE_VIDEO_BYTES = 20 * 1024 * 1024


def text_part(text: str) -> dict[str, Any]:
    """A plain-text content part."""
    return {"type": "text", "text": text}


def video_part(raw_bytes: bytes, *, mime: str = DEFAULT_VIDEO_MIME) -> dict[str, Any]:
    """A base64 data-URL video content part (OpenRouter→Gemini ``video_url`` shape).

    Fail-closed BEFORE encoding: rejects an unsupported MIME or an over-cap payload.
    """
    if mime not in SUPPORTED_VIDEO_MIMES:
        raise ValueError(f"unsupported video mime: {mime!r}")
    if len(raw_bytes) > MAX_INLINE_VIDEO_BYTES:
        raise ValueError(f"video exceeds inline cap of {MAX_INLINE_VIDEO_BYTES} bytes")
    b64 = base64.b64encode(raw_bytes).decode("ascii")
    return {"type": "video_url", "video_url": {"url": f"data:{mime};base64,{b64}"}}
