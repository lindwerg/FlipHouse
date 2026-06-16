"""Per-profile OpenRouter model routing (doc 04 §2.3).

Model slugs are pinned here at build-time — never hard-coded at the call site —
because the model line-up on openrouter.ai/models changes over time. ``founder``
reviews these slugs at CHECKPOINT A and may edit them without touching adapter
logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class Profile(StrEnum):
    """The two LLM workloads with opposite cost/quality profiles."""

    SCORING = "scoring"  # cheap, high-volume virality scoring
    OFFER_MATCH = "offer_match"  # strong models, escalate on edge cases


@dataclass(frozen=True)
class RouteConfig:
    models: tuple[str, ...]  # priority order -> OpenRouter `models` fallback array
    provider: dict[str, Any]


# `require_parameters: true` is the critical guard — route only to providers that
# truly support `response_format` json_schema, else strict mode silently degrades
# to free text (doc 04 §2.3).
ROUTES: dict[Profile, RouteConfig] = {
    Profile.SCORING: RouteConfig(
        models=("google/gemini-2.5-flash", "openai/gpt-5-mini", "deepseek/deepseek-chat"),
        provider={"sort": "price", "require_parameters": True},
    ),
    Profile.OFFER_MATCH: RouteConfig(
        models=("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"),
        provider={"require_parameters": True},
    ),
}
