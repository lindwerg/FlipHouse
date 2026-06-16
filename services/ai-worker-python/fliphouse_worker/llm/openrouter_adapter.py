"""OpenRouter adapter — OpenAI-compatible LLM client (doc 04 §2.6).

Drop-in replacement for raw Gemini/OpenAI calls: switching providers is just a
``base_url`` + key change. Per-profile model routing (:mod:`.routes`), strict
``response_format: json_schema``, attribution headers, and a retry/backoff loop
that owns retries exclusively (the OpenAI client is constructed with
``max_retries=0`` so call counts stay deterministic).
"""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import dataclass, field
from typing import Any

from openai import APIConnectionError, APIStatusError, OpenAI, RateLimitError

from .routes import ROUTES, Profile

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
_MAX_BACKOFF_SECONDS = 30


@dataclass
class LLMResult:
    data: dict[str, Any]
    model_used: str
    raw_usage: dict[str, Any] = field(default_factory=dict)


class OpenRouterAdapter:
    """OpenAI-compatible OpenRouter client returning validated JSON."""

    def __init__(
        self,
        *,
        base_url: str | None = None,
        api_key: str | None = None,
        app_url: str = "https://fliphouse.app",
        app_title: str = "FlipHouse",
        max_retries: int = 4,
    ) -> None:
        self._client = OpenAI(
            base_url=base_url or OPENROUTER_BASE_URL,
            api_key=api_key or os.environ["OPENROUTER_API_KEY"],
            # The adapter's own loop is the sole retry authority.
            max_retries=0,
            default_headers={"HTTP-Referer": app_url, "X-OpenRouter-Title": app_title},
        )
        self._max_retries = max_retries

    def complete_json(
        self,
        *,
        profile: Profile,
        system: str,
        user: str,
        schema_name: str,
        schema: dict[str, Any],
        temperature: float = 0.2,
        cache_static_prefix: bool = False,
    ) -> LLMResult:
        route = ROUTES[profile]
        sys_content: Any = system
        if cache_static_prefix:  # Anthropic explicit cache; no-op for OpenAI/Gemini auto-cache
            sys_content = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        body = dict(
            model=route.models[0],
            extra_body={"models": list(route.models), "provider": route.provider},
            messages=[
                {"role": "system", "content": sys_content},
                {"role": "user", "content": user},
            ],
            temperature=temperature,
            response_format={
                "type": "json_schema",
                "json_schema": {"name": schema_name, "strict": True, "schema": schema},
            },
        )
        resp = self._call_with_retry(body)
        choice = resp.choices[0].message.content
        if choice is None:
            # content is None on finish_reason=tool_calls/content_filter or a
            # malformed provider response — surface a clear error, never let
            # json.loads(None) raise a confusing TypeError downstream.
            raise ValueError("Non-JSON despite strict schema: model returned no content")
        try:
            data = json.loads(choice)
        except json.JSONDecodeError as e:
            raise ValueError(f"Non-JSON despite strict schema: {choice[:200]}") from e
        usage = getattr(resp, "usage", None)
        return LLMResult(
            data=data,
            model_used=getattr(resp, "model", None) or route.models[0],
            raw_usage=usage.model_dump() if usage else {},
        )

    def _call_with_retry(self, body: dict[str, Any]):
        last_exc: Exception | None = None
        for attempt in range(self._max_retries):
            try:
                return self._client.chat.completions.create(**body)
            except (RateLimitError, APIConnectionError) as e:  # 429 / network
                last_exc = e
            except APIStatusError as e:  # 402, 5xx, other
                if e.status_code == 402:
                    raise RuntimeError("OpenRouter credits exhausted (402)") from e
                if not (e.status_code and e.status_code >= 500):
                    raise  # non-retryable 4xx — propagate the SDK error as-is
                last_exc = e
            # Retryable failure: back off, but not after the final attempt.
            if attempt < self._max_retries - 1:
                self._backoff(attempt, last_exc)
        raise RuntimeError("OpenRouter call failed after retries") from last_exc

    @staticmethod
    def _backoff(attempt: int, err: Exception) -> None:
        time.sleep(min(2**attempt + random.random(), _MAX_BACKOFF_SECONDS))
