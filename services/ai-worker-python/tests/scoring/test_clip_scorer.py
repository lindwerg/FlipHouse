"""Wiring tests for ClipScorer (P2-S3) — adapter call shape, parse, bounded retry.

No network: the OpenRouter chat endpoint is intercepted with respx. The adapter
is always built with an explicit api_key so CI never reads OPENROUTER_API_KEY.
"""

import json

import httpx
import pytest
import respx

from fliphouse_worker.eval import LabeledClip
from fliphouse_worker.llm import OpenRouterAdapter
from fliphouse_worker.scoring import (
    MEDIA_SYSTEM_PROMPT,
    PER_CLIP_VIRALITY_SCHEMA,
    SYSTEM_PROMPT,
    ClipScorer,
    aggregate_score,
)

CHAT_URL = "https://openrouter.ai/api/v1/chat/completions"


def _valid(**overrides) -> dict:
    base = {
        "rationale": "Strong hook and self-contained payoff.",
        "hook": 80,
        "emotion": 60,
        "payoff": 75,
        "visual": -1,
        "audio": -1,
        "pacing": 55,
        "confidence": 70,
        "modalities_used": ["text"],
    }
    base.update(overrides)
    return base


def _completion(content: str, *, model: str = "google/gemini-3.1-flash-lite") -> dict:
    return {
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
        "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
    }


def _score_response(sub: dict) -> httpx.Response:
    return httpx.Response(200, json=_completion(json.dumps(sub)))


def _scorer() -> ClipScorer:
    return ClipScorer(OpenRouterAdapter(api_key="test-key"))


def _sent_body(route) -> dict:
    return json.loads(route.calls.last.request.content)


@respx.mock
def test_clip_scorer_sends_scoring_profile_and_schema():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("nobody talks about this")
    body = _sent_body(route)
    assert body["models"] == ["google/gemini-3.1-flash-lite", "google/gemini-2.5-flash-lite"]
    rf = body["response_format"]
    assert rf["json_schema"]["name"] == "per_clip_virality"
    assert rf["json_schema"]["strict"] is True
    assert rf["json_schema"]["schema"] == PER_CLIP_VIRALITY_SCHEMA


@respx.mock
def test_clip_scorer_uses_temperature_zero():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("text")
    assert _sent_body(route)["temperature"] == 0.0


@respx.mock
def test_clip_scorer_caches_static_prefix():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("text")
    system_msg = _sent_body(route)["messages"][0]["content"]
    assert isinstance(system_msg, list)
    assert system_msg[0]["cache_control"] == {"type": "ephemeral"}


@respx.mock
def test_clip_scorer_parses_subscores_and_aggregates():
    sub = _valid(hook=100, payoff=100, emotion=0, pacing=0)
    respx.post(CHAT_URL).mock(return_value=_score_response(sub))
    scored = _scorer().score_clip("text")
    assert scored.aggregate == aggregate_score(sub, ["text"])
    assert scored.sub_scores["hook"] == 100
    assert scored.confidence == 70
    assert scored.modalities_used == ["text"]
    assert scored.model_used == "google/gemini-3.1-flash-lite"
    assert scored.raw_usage["total_tokens"] == 2


@respx.mock
def test_clip_scorer_applies_duration():
    respx.post(CHAT_URL).mock(
        return_value=_score_response(_valid(hook=50, payoff=50, emotion=50, pacing=50))
    )
    scored = _scorer().score_clip("text", duration_s=8)
    assert scored.aggregate == 30.0  # 50 * length_factor(8)=0.60


@respx.mock
def test_clip_scorer_retries_once_on_invalid_then_succeeds():
    # First response is well-formed JSON (complete_json succeeds) but rubric-invalid
    # (missing 'pacing' → _validate raises) → scorer re-asks → second succeeds.
    bad = _valid()
    del bad["pacing"]
    route = respx.post(CHAT_URL).mock(side_effect=[_score_response(bad), _score_response(_valid())])
    scored = _scorer().score_clip("text")
    assert route.call_count == 2
    assert scored.sub_scores["pacing"] == 55


@respx.mock
def test_clip_scorer_raises_after_retry_still_invalid():
    bad = _valid()
    del bad["hook"]
    route = respx.post(CHAT_URL).mock(side_effect=[_score_response(bad), _score_response(bad)])
    with pytest.raises(ValueError):
        _scorer().score_clip("text")
    assert route.call_count == 2


@respx.mock
def test_score_clips_returns_float_per_clip_id():
    respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    clips = [LabeledClip("c1", "first", 50), LabeledClip("c2", "second", 60)]
    out = _scorer().score_clips(clips)
    assert set(out) == {"c1", "c2"}
    assert all(isinstance(v, float) for v in out.values())


# ── media path (P2-S4) ───────────────────────────────────────────────────


@respx.mock
def test_clip_scorer_media_path_sends_multimodal_profile_and_video():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("txt", video=b"ABC")
    body = _sent_body(route)
    assert body["models"] == ["google/gemini-3.5-flash", "google/gemini-2.5-flash"]
    assert body["provider"] == {"require_parameters": True, "only": ["google-vertex"]}
    content = body["messages"][1]["content"]
    assert content[0] == {"type": "text", "text": "txt"}
    assert content[1]["type"] == "video_url"
    assert content[1]["video_url"]["url"].startswith("data:video/mp4;base64,")


@respx.mock
def test_clip_scorer_media_path_uses_av_activating_system_prompt():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("txt", video=b"ABC")
    system_text = _sent_body(route)["messages"][0]["content"][0]["text"]
    assert system_text == MEDIA_SYSTEM_PROMPT  # A/V prompt, not the text-only one
    assert system_text != SYSTEM_PROMPT


@respx.mock
def test_clip_scorer_text_path_uses_text_only_system_prompt():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("txt")
    system_text = _sent_body(route)["messages"][0]["content"][0]["text"]
    assert system_text == SYSTEM_PROMPT


@respx.mock
def test_clip_scorer_media_reask_preserves_video_and_uses_media_nudge():
    bad = _valid()
    del bad["pacing"]
    route = respx.post(CHAT_URL).mock(side_effect=[_score_response(bad), _score_response(_valid())])
    _scorer().score_clip("txt", video=b"ABC")
    assert route.call_count == 2
    content = _sent_body(route)["messages"][1]["content"]
    assert content[0]["text"].startswith("txt")
    assert content[0]["text"] != "txt"  # nudge appended
    assert content[1]["type"] == "video_url"  # video preserved on the re-ask
    assert 'modalities_used=["text"]' not in content[0]["text"]  # not the text-only sentinel


@respx.mock
def test_clip_scorer_text_path_unchanged_str_user():
    route = respx.post(CHAT_URL).mock(return_value=_score_response(_valid()))
    _scorer().score_clip("txt")
    body = _sent_body(route)
    assert body["models"] == ["google/gemini-3.1-flash-lite", "google/gemini-2.5-flash-lite"]
    assert body["provider"] == {"require_parameters": True}
    assert body["messages"][1]["content"] == "txt"


@respx.mock
def test_clip_scorer_text_reask_uses_text_nudge_str():
    bad = _valid()
    del bad["pacing"]
    route = respx.post(CHAT_URL).mock(side_effect=[_score_response(bad), _score_response(_valid())])
    _scorer().score_clip("txt")
    content = _sent_body(route)["messages"][1]["content"]
    assert isinstance(content, str)
    assert content.startswith("txt") and content != "txt"
