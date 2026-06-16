"""Tests for the lifted SamurAIGPT highlight-selection engine (P2.1).

The engine is the AI-clipping core: a transcript goes in, ranked viral
highlights come out. The LLM is injected via ``llm_fn`` (no hardcoded /
paid provider in our tree), so every test here drives a deterministic fake
LLM — no network, no API keys.
"""

import ast
import inspect
import json
from pathlib import Path

import pytest

from fliphouse_worker.engine import (
    dedupe_highlights,
    get_highlights,
    select_highlights,
)
from fliphouse_worker.engine import highlights as hl

CONTENT_JSON = '{"content_type": "interview", "density": "high"}'


class FakeLLM:
    """Deterministic ``llm_fn``: content-type prompt → CONTENT_JSON,
    highlight prompts → next queued response (cycling on the last one)."""

    def __init__(self, highlight_responses):
        self.highlight_responses = list(highlight_responses)
        self.calls = []
        self._idx = 0

    def __call__(self, prompt: str) -> str:
        self.calls.append(prompt)
        if "classify the content type" in prompt:
            return CONTENT_JSON
        resp = self.highlight_responses[min(self._idx, len(self.highlight_responses) - 1)]
        self._idx += 1
        return resp

    @property
    def highlight_call_count(self) -> int:
        return sum(1 for p in self.calls if "classify the content type" not in p)


def _highlights_json(items) -> str:
    return json.dumps({"highlights": items})


def _seg(start, end, text="hello world"):
    return {"start": start, "end": end, "text": text}


def _transcript(duration, segments):
    return {"duration": duration, "segments": segments}


# ── 1–3: seam / discard ──────────────────────────────────────────────────


def test_engine_exposes_selection_seam():
    assert callable(select_highlights)
    assert callable(get_highlights)
    assert "llm_fn" in inspect.signature(select_highlights).parameters
    assert "llm_fn" in inspect.signature(get_highlights).parameters


def test_no_paid_or_unlicensed_provider_in_engine():
    engine_dir = Path(hl.__file__).parent
    assert not (engine_dir / "muapi.py").exists()
    banned = {"muapi", "genai", "google.generativeai"}
    for py in engine_dir.glob("*.py"):
        tree = ast.parse(py.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in banned, f"{py.name} imports {alias.name}"
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                assert mod not in banned, f"{py.name} imports from {mod}"
                assert "muapi" not in mod, f"{py.name} imports from {mod}"


def test_highlight_selector_requires_injected_llm():
    transcript = _transcript(120, [_seg(0, 10)])
    with pytest.raises(TypeError):
        get_highlights(transcript)  # llm_fn is required (keyword-only, no default)


# ── 4–7: selection behavior ──────────────────────────────────────────────


def test_returns_ranked_clips_sorted_by_score_desc():
    fake = FakeLLM(
        [
            _highlights_json(
                [
                    {
                        "title": "A",
                        "start_time": 0,
                        "end_time": 30,
                        "score": 40,
                        "hook_sentence": "h",
                        "virality_reason": "r",
                    },
                    {
                        "title": "B",
                        "start_time": 40,
                        "end_time": 70,
                        "score": 90,
                        "hook_sentence": "h",
                        "virality_reason": "r",
                    },
                    {
                        "title": "C",
                        "start_time": 80,
                        "end_time": 110,
                        "score": 70,
                        "hook_sentence": "h",
                        "virality_reason": "r",
                    },
                ]
            )
        ]
    )
    result = select_highlights(_transcript(120, [_seg(0, 10)]), llm_fn=fake)
    assert [h["score"] for h in result] == [90, 70, 40]


def test_clip_bounds_clamped_within_source_duration():
    raw = [
        {"title": "ok", "start_time": 10, "end_time": 200, "score": 50},  # end clamped → 120
        {"title": "neg", "start_time": -5, "end_time": 20, "score": 50},  # start < 0 → dropped
        {
            "title": "past",
            "start_time": 130,
            "end_time": 140,
            "score": 50,
        },  # clamp → end<=start dropped
        {
            "title": "coerce",
            "start_time": 5,
            "end_time": 25,
            "score": "abc",
        },  # non-numeric score → 0
        {
            "title": "badstart",
            "start_time": "xx",
            "end_time": 10,
            "score": 5,
        },  # non-numeric start → dropped
        42,  # non-dict → skipped
    ]
    cleaned = hl._sanitize_highlights(raw, duration=120)
    assert len(cleaned) == 2
    assert cleaned[0]["end_time"] == 120
    assert cleaned[1]["score"] == 0
    # non-list input and unbounded (duration<=0) input
    assert hl._sanitize_highlights("not a list", duration=120) == []
    unbounded = hl._sanitize_highlights(
        [{"title": "x", "start_time": 5, "end_time": 9999, "score": 10}], duration=0
    )
    assert unbounded[0]["end_time"] == 9999  # no clamp when duration<=0


def test_dedupe_drops_overlapping_lower_score():
    kept = dedupe_highlights(
        [
            {"title": "high", "start_time": 0, "end_time": 60, "score": 90},
            {
                "title": "low",
                "start_time": 10,
                "end_time": 50,
                "score": 40,
            },  # >50% overlap → dropped
            {"title": "far", "start_time": 200, "end_time": 240, "score": 30},  # disjoint → kept
        ]
    )
    titles = {h["title"] for h in kept}
    assert titles == {"high", "far"}


def test_empty_transcript_yields_no_clips():
    fake = FakeLLM([_highlights_json([])])
    assert select_highlights(_transcript(0, []), llm_fn=fake) == []
    assert fake.calls == []  # graceful early-out, no LLM call


# ── 8: JSON parsing ──────────────────────────────────────────────────────


def test_parses_json_wrapped_in_markdown_fences():
    assert hl._parse_json_loose('```json\n{"a": 1}\n```') == {"a": 1}
    assert hl._parse_json_loose('noise {"a": 2} trailing') == {"a": 2}  # brace extraction
    with pytest.raises(json.JSONDecodeError):
        hl._parse_json_loose("not json at all")


# ── 9–10: retry semantics ────────────────────────────────────────────────


def test_retries_on_invalid_output_then_succeeds():
    fake = FakeLLM(
        [
            "garbage not json",
            _highlights_json(
                [
                    {
                        "title": "A",
                        "start_time": 0,
                        "end_time": 30,
                        "score": 80,
                        "hook_sentence": "h",
                        "virality_reason": "r",
                    },
                ]
            ),
        ]
    )
    result = hl.call_highlight_api(
        "transcript text",
        {"content_type": "interview", "density": "high"},
        duration=120,
        num_clips=1,
        llm_fn=fake,
    )
    assert result["highlights"][0]["score"] == 80
    assert fake.highlight_call_count == 2


def test_raises_after_max_attempts_on_invalid_output():
    fake = FakeLLM(["still garbage"])
    with pytest.raises(RuntimeError):
        hl.call_highlight_api(
            "transcript text",
            {"content_type": "other", "density": "medium"},
            duration=120,
            num_clips=1,
            llm_fn=fake,
        )
    assert fake.highlight_call_count == hl.MAX_HIGHLIGHT_API_ATTEMPTS


def test_raises_when_valid_json_has_no_usable_highlights():
    fake = FakeLLM([_highlights_json([])])  # valid JSON, but zero highlights every attempt
    with pytest.raises(RuntimeError):
        hl.call_highlight_api(
            "transcript text",
            {"content_type": "other", "density": "medium"},
            duration=120,
            num_clips=1,
            llm_fn=fake,
        )
    assert fake.highlight_call_count == hl.MAX_HIGHLIGHT_API_ATTEMPTS


# ── 11: long-video chunking ──────────────────────────────────────────────


def test_long_video_is_chunked_with_offset_applied():
    segments = [_seg(i, i + 5) for i in range(0, 1990, 100)]
    transcript = _transcript(2000, segments)  # >= LONG_VIDEO_THRESHOLD → chunked
    assert transcript["duration"] >= hl.LONG_VIDEO_THRESHOLD
    fake = FakeLLM(
        [
            _highlights_json(
                [
                    {
                        "title": "clip",
                        "start_time": 5,
                        "end_time": 50,
                        "score": 80,
                        "hook_sentence": "h",
                        "virality_reason": "r",
                    },
                ]
            )
        ]
    )
    result = select_highlights(transcript, llm_fn=fake, num_clips=2)
    assert len(result) >= 2  # one highlight per chunk, disjoint after offset
    assert any(h["start_time"] > 1000 for h in result)  # second chunk offset applied


# ── 12: content-type detection fallback ──────────────────────────────────


def test_content_type_detection_falls_back_on_error():
    def boom(_prompt: str) -> str:
        raise RuntimeError("llm down")

    info = hl.detect_content_type(_transcript(120, [_seg(0, 10)]), llm_fn=boom)
    assert info == {"content_type": "other", "density": "medium"}
