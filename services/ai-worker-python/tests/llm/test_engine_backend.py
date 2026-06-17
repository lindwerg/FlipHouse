"""Tests for the engine↔adapter bridge (P2-S2).

``EngineLLMBackend`` adapts the OpenRouter adapter to the engine's
``LLMFn = Callable[[str], str]`` seam so the highlight engine gets OpenRouter
routing/retries and so per-job token usage can be captured (for the S7 cost log).
Unit tests drive a stub adapter; one end-to-end test wires the real adapter
(through ``respx``) into ``select_highlights``.
"""

import json

import httpx
import pytest
import respx

from fliphouse_worker.engine import select_highlights
from fliphouse_worker.llm import EngineLLMBackend, LLMResult, OpenRouterAdapter, Profile
from fliphouse_worker.llm import openrouter_adapter as ora

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


class StubAdapter:
    """Records ``complete`` kwargs and returns queued ``LLMResult``s."""

    def __init__(self, results):
        self._results = list(results)
        self.calls: list[dict] = []
        self._idx = 0

    def complete(self, **kwargs) -> LLMResult:
        self.calls.append(kwargs)
        result = self._results[min(self._idx, len(self._results) - 1)]
        self._idx += 1
        return result


def _result(text="", *, model_used="m", usage=None) -> LLMResult:
    return LLMResult(data={}, model_used=model_used, raw_usage=usage or {}, text=text)


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    monkeypatch.setattr(ora.time, "sleep", lambda _seconds: None)


# ── callable seam ────────────────────────────────────────────────────────


def test_backend_is_callable_returns_text():
    backend = EngineLLMBackend(StubAdapter([_result("payload")]))
    assert backend("prompt") == "payload"


def test_backend_uses_scoring_profile_by_default():
    stub = StubAdapter([_result("x")])
    EngineLLMBackend(stub)("prompt")
    assert stub.calls[0]["profile"] is Profile.SCORING


def test_backend_honors_explicit_profile():
    stub = StubAdapter([_result("x")])
    EngineLLMBackend(stub, profile=Profile.SCORING_MULTIMODAL)("prompt")
    assert stub.calls[0]["profile"] is Profile.SCORING_MULTIMODAL


# ── usage / model capture ────────────────────────────────────────────────


def test_backend_records_last_model_used():
    backend = EngineLLMBackend(
        StubAdapter([_result("a", model_used="m1"), _result("b", model_used="m2")])
    )
    backend("p1")
    backend("p2")
    assert backend.last_model_used == "m2"


def test_backend_accumulates_usage_across_calls():
    usage = {"prompt_tokens": 5, "completion_tokens": 1, "total_tokens": 6}
    backend = EngineLLMBackend(StubAdapter([_result("a", usage=usage), _result("b", usage=usage)]))
    backend("p1")
    backend("p2")
    assert backend.raw_usage["total_tokens"] == 12
    assert backend.raw_usage["prompt_tokens"] == 10


def test_backend_accumulates_with_empty_usage():
    backend = EngineLLMBackend(StubAdapter([_result("a", usage={})]))
    backend("prompt")
    assert backend.raw_usage["total_tokens"] == 0


# ── end-to-end: real adapter → engine ────────────────────────────────────


@respx.mock
def test_backend_plugs_into_select_highlights():
    content_json = json.dumps({"content_type": "interview", "density": "high"})
    highlights_json = json.dumps(
        {
            "highlights": [
                {
                    "title": "The big reveal",
                    "start_time": 10.0,
                    "end_time": 70.0,
                    "score": 92,
                    "hook_sentence": "Nobody talks about this",
                    "virality_reason": "counter-intuitive claim",
                }
            ]
        }
    )

    def _body(content: str) -> dict:
        return {
            "id": "chatcmpl-test",
            "object": "chat.completion",
            "created": 0,
            "model": "google/gemini-3.1-flash-lite",
            "choices": [
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": content},
                    "finish_reason": "stop",
                }
            ],
            "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
        }

    respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(200, json=_body(content_json)),
            httpx.Response(200, json=_body(highlights_json)),
        ]
    )

    backend = EngineLLMBackend(OpenRouterAdapter(api_key="test-key"))
    transcript = {
        "duration": 120.0,
        "segments": [{"start": 10.0, "end": 70.0, "text": "nobody talks about this secret"}],
    }
    highlights = select_highlights(transcript, llm_fn=backend, num_clips=3)

    assert len(highlights) == 1
    assert highlights[0]["title"] == "The big reveal"
    assert backend.last_model_used == "google/gemini-3.1-flash-lite"
    assert backend.raw_usage["total_tokens"] == 4  # two calls × 2 tokens


# ── EngineHighlightBackend (reliable recall seam) ─────────────────────────


class StubJsonAdapter:
    """Records complete_json kwargs and returns queued LLMResults."""

    def __init__(self, results):
        self._results = list(results)
        self.calls: list[dict] = []
        self._idx = 0

    def complete_json(self, **kwargs) -> LLMResult:
        self.calls.append(kwargs)
        result = self._results[min(self._idx, len(self._results) - 1)]
        self._idx += 1
        return result


def test_highlight_backend_returns_parsed_dict_and_captures_usage():
    from fliphouse_worker.llm import EngineHighlightBackend
    from fliphouse_worker.llm.schemas import HIGHLIGHTS_SCHEMA

    data = {
        "highlights": [
            {
                "title": "A",
                "start_time": 1,
                "end_time": 9,
                "score": 80,
                "hook_sentence": "h",
                "virality_reason": "r",
            }
        ]
    }
    adapter = StubJsonAdapter(
        [
            LLMResult(data=data, model_used="gemini", raw_usage={"total_tokens": 7}),
        ]
    )
    backend = EngineHighlightBackend(adapter)  # type: ignore[arg-type]

    out = backend("prompt")

    assert out == data
    assert adapter.calls[0]["schema"] is HIGHLIGHTS_SCHEMA
    assert adapter.calls[0]["schema_name"] == "highlights"
    assert backend.last_model_used == "gemini"
    assert backend.raw_usage["total_tokens"] == 7


def test_highlights_schema_is_gemini_safe_subset():
    from fliphouse_worker.llm.schemas import HIGHLIGHTS_SCHEMA

    text = json.dumps(HIGHLIGHTS_SCHEMA)
    assert HIGHLIGHTS_SCHEMA["type"] == "object"
    assert HIGHLIGHTS_SCHEMA["additionalProperties"] is False
    item = HIGHLIGHTS_SCHEMA["properties"]["highlights"]["items"]
    assert item["additionalProperties"] is False
    assert len(item["required"]) == 6
    for banned in ("enum", "minItems", "maxItems", "$ref", "format", "oneOf", "anyOf", "allOf"):
        assert banned not in text
