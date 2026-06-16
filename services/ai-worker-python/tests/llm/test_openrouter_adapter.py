"""Tests for the OpenRouter adapter (P2.2).

The adapter is the concrete LLM client behind the engine's injected ``llm_fn``
seam: an OpenAI-compatible call to OpenRouter with per-profile model routing,
strict ``response_format: json_schema``, retry/backoff and attribution headers
(doc 04 §2.2–2.6). No real network is hit — every call is intercepted with
``respx``, and the retry backoff's ``time.sleep`` is monkeypatched away.
"""

import json

import httpx
import pytest
import respx
from openai import BadRequestError

from fliphouse_worker.llm import LLMResult, OpenRouterAdapter, Profile
from fliphouse_worker.llm import openrouter_adapter as ora
from fliphouse_worker.llm.schemas import VIRALITY_SCORE_SCHEMA

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"

# Doc 04 §2.4 virality_score schema — the contract this adapter pins against
# drift. Kept as a literal here so the contract test compares two independent
# sources rather than the module against itself.
DOC04_VIRALITY_SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "hook_strength": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["score", "hook_strength", "tags", "reason"],
    "additionalProperties": False,
}


def _completion(
    content: str | None, *, model: str = "google/gemini-2.5-flash", usage: bool = True
) -> dict:
    """A minimal OpenAI ChatCompletion body the SDK can parse."""
    body: dict = {
        "id": "chatcmpl-test",
        "object": "chat.completion",
        "created": 0,
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
    }
    if usage:
        body["usage"] = {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2}
    return body


VALID_SCORE = json.dumps(
    {"score": 88, "hook_strength": 0.9, "tags": ["finance"], "reason": "strong open"}
)


@pytest.fixture
def adapter() -> OpenRouterAdapter:
    return OpenRouterAdapter(api_key="test-key")


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Backoff must not actually sleep during retry tests."""
    monkeypatch.setattr(ora.time, "sleep", lambda _seconds: None)


def _call(adapter: OpenRouterAdapter, *, profile: Profile = Profile.SCORING, **kw) -> LLMResult:
    return adapter.complete_json(
        profile=profile,
        system="rubric",
        user="transcript",
        schema_name="virality_score",
        schema=VIRALITY_SCORE_SCHEMA,
        **kw,
    )


def _sent_body(route) -> dict:
    return json.loads(route.calls.last.request.content)


# ── routing ──────────────────────────────────────────────────────────────


@respx.mock
def test_scoring_profile_routes_to_cheap_models_in_order(adapter):
    # P2-S2 re-plan: SCORING is all-Gemini via OpenRouter — deepseek-chat (rejects
    # strict json_schema) and sort:"price" (could route to a provider without
    # video/strict support) are removed.
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter, profile=Profile.SCORING)
    body = _sent_body(route)
    assert body["models"] == [
        "google/gemini-3.1-flash-lite",
        "google/gemini-2.5-flash-lite",
    ]
    assert body["provider"] == {"require_parameters": True}


@respx.mock
def test_scoring_multimodal_profile_routes_to_av_models(adapter):
    # P2-S2: Stage B (native A/V) profile — gemini-3.5-flash via OpenRouter.
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter, profile=Profile.SCORING_MULTIMODAL)
    body = _sent_body(route)
    assert body["models"] == [
        "google/gemini-3.5-flash",
        "google/gemini-2.5-flash",
    ]
    assert body["provider"] == {"require_parameters": True}


@respx.mock
def test_offer_match_profile_uses_strong_models(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter, profile=Profile.OFFER_MATCH)
    body = _sent_body(route)
    assert body["models"] == [
        "anthropic/claude-sonnet-4.5",
        "openai/gpt-5",
        "google/gemini-2.5-pro",
    ]
    assert body["provider"] == {"require_parameters": True}


# ── request shape ─────────────────────────────────────────────────────────


@respx.mock
def test_sends_json_schema_strict_response_format(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter)
    rf = _sent_body(route)["response_format"]
    assert rf["type"] == "json_schema"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["name"] == "virality_score"


@respx.mock
def test_attribution_headers_present(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter)
    headers = route.calls.last.request.headers
    assert headers["HTTP-Referer"] == "https://fliphouse.app"
    assert headers["X-OpenRouter-Title"] == "FlipHouse"


@respx.mock
def test_caches_static_prefix_when_requested(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE))
    )
    _call(adapter, cache_static_prefix=True)
    system_msg = _sent_body(route)["messages"][0]["content"]
    assert system_msg == [
        {"type": "text", "text": "rubric", "cache_control": {"type": "ephemeral"}}
    ]


# ── parsing ────────────────────────────────────────────────────────────────


@respx.mock
def test_parses_valid_json_response(adapter):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE, model="openai/gpt-5-mini"))
    )
    result = _call(adapter)
    assert result.data == {
        "score": 88,
        "hook_strength": 0.9,
        "tags": ["finance"],
        "reason": "strong open",
    }
    assert result.model_used == "openai/gpt-5-mini"
    assert result.raw_usage["total_tokens"] == 2


@respx.mock
def test_parses_response_without_usage(adapter):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion(VALID_SCORE, usage=False))
    )
    result = _call(adapter)
    assert result.raw_usage == {}


@respx.mock
def test_raises_on_non_json_despite_strict(adapter):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(200, json=_completion("totally not json"))
    )
    with pytest.raises(ValueError, match="Non-JSON despite strict schema"):
        _call(adapter)


@respx.mock
def test_raises_on_null_content(adapter):
    # finish_reason=tool_calls/content_filter (or a malformed provider) → content None.
    # Must surface a clear ValueError, never a raw TypeError from json.loads(None).
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(None)))
    with pytest.raises(ValueError, match="Non-JSON despite strict schema"):
        _call(adapter)


# ── complete() text path (engine seam) ──────────────────────────────────────


def _complete(adapter: OpenRouterAdapter, *, profile: Profile = Profile.SCORING) -> LLMResult:
    return adapter.complete(profile=profile, system="", user="prompt")


@respx.mock
def test_complete_omits_response_format(adapter):
    # The text path must not constrain the model with a json_schema — the engine
    # embeds its own JSON instructions and parses loosely (S3 owns strict schema).
    route = respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion("hello")))
    _complete(adapter)
    assert "response_format" not in _sent_body(route)


@respx.mock
def test_complete_returns_text_and_metadata(adapter):
    respx.post(CHAT_URL).mock(
        return_value=httpx.Response(
            200, json=_completion("raw model text", model="google/gemini-3.1-flash-lite")
        )
    )
    result = _complete(adapter)
    assert result.text == "raw model text"
    assert result.data == {}
    assert result.model_used == "google/gemini-3.1-flash-lite"
    assert result.raw_usage["total_tokens"] == 2


@respx.mock
def test_complete_returns_empty_text_on_null_content(adapter):
    # The engine owns retry/fallback; complete() must return "" (not raise) so a
    # single null response flows into the engine's loose parser → retry loop.
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(None)))
    assert _complete(adapter).text == ""


@respx.mock
def test_complete_json_text_field_empty(adapter):
    # Strict-JSON results carry no raw text — pin the new field on the strict path.
    respx.post(CHAT_URL).mock(return_value=httpx.Response(200, json=_completion(VALID_SCORE)))
    assert _call(adapter).text == ""


# ── retry / fallback ─────────────────────────────────────────────────────


@respx.mock
def test_retries_on_429_then_succeeds(adapter):
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(429, json={"error": {"message": "rate limited"}}),
            httpx.Response(200, json=_completion(VALID_SCORE)),
        ]
    )
    result = _call(adapter)
    assert route.call_count == 2
    assert result.data["score"] == 88


@respx.mock
def test_retries_on_5xx_then_succeeds(adapter):
    route = respx.post(CHAT_URL).mock(
        side_effect=[
            httpx.Response(503, json={"error": {"message": "upstream down"}}),
            httpx.Response(200, json=_completion(VALID_SCORE)),
        ]
    )
    result = _call(adapter)
    assert route.call_count == 2
    assert result.data["score"] == 88


@respx.mock
def test_402_is_fatal_no_retry(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(402, json={"error": {"message": "negative balance"}})
    )
    with pytest.raises(RuntimeError, match="credits exhausted"):
        _call(adapter)
    assert route.call_count == 1


@respx.mock
def test_4xx_non_402_reraises(adapter):
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(400, json={"error": {"message": "bad request"}})
    )
    with pytest.raises(BadRequestError):
        _call(adapter)
    assert route.call_count == 1


@respx.mock
def test_retries_exhausted_raises():
    adapter = OpenRouterAdapter(api_key="test-key", max_retries=2)
    route = respx.post(CHAT_URL).mock(
        return_value=httpx.Response(429, json={"error": {"message": "rate limited"}})
    )
    with pytest.raises(RuntimeError, match="after retries"):
        _call(adapter)
    assert route.call_count == 2


# ── schema contract ─────────────────────────────────────────────────────


def test_score_schema_matches_doc04_contract():
    assert VIRALITY_SCORE_SCHEMA == DOC04_VIRALITY_SCORE_SCHEMA
