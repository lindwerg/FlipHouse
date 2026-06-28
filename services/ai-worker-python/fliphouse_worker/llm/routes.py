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
    """The LLM workloads with distinct cost/quality profiles."""

    SCORING = "scoring"  # Stage A: cheap text-only virality scoring
    SCORING_MULTIMODAL = "scoring_multimodal"  # Stage B: native A/V re-scoring of finalists
    OFFER_MATCH = "offer_match"  # strong models, escalate on edge cases
    KEYWORD = "keyword"  # P3-A4: per-line keyword-salience text task (cheap, like SCORING)


@dataclass(frozen=True)
class RouteConfig:
    models: tuple[str, ...]  # priority order -> OpenRouter `models` fallback array
    provider: dict[str, Any]
    # Output cap. Recall must close a ~12-item JSON array; without it Gemini can
    # truncate (finish_reason=length) → invalid JSON → the real 4/7-chunk failure.
    max_tokens: int | None = None


# `require_parameters: true` is the critical guard — route only to providers that
# truly support `response_format` json_schema, else strict mode silently degrades
# to free text (doc 04 §2.3).
#
# P2-S2 re-plan (founder, all-OpenRouter + all-Gemini): SCORING dropped
# `deepseek-chat` (rejects strict json_schema) and `sort:"price"` (could route to
# a provider lacking video/strict support). SCORING_MULTIMODAL (Stage B native
# A/V) routes to gemini-3.5-flash.
ROUTES: dict[Profile, RouteConfig] = {
    Profile.SCORING: RouteConfig(
        models=("google/gemini-3.1-flash-lite", "google/gemini-2.5-flash-lite"),
        provider={"require_parameters": True},
        max_tokens=4096,
    ),
    Profile.SCORING_MULTIMODAL: RouteConfig(
        models=("google/gemini-3.5-flash", "google/gemini-2.5-flash"),
        provider={"require_parameters": True},
    ),
    Profile.OFFER_MATCH: RouteConfig(
        models=("anthropic/claude-sonnet-4.5", "openai/gpt-5", "google/gemini-2.5-pro"),
        provider={"require_parameters": True},
    ),
    # P3-A4: one {line,keyword_index} row per caption line. Worst case = a 180s clip
    # (render.MAX_CLIP_DURATION_S) ~225 lines * ~14 tok/row ≈ 3.1k tok; 4096 (matching
    # SCORING) clears it with slack so the longest, most caption-dense clips don't truncate
    # (finish_reason=length → JSON parse raises → fail-open all-None).
    Profile.KEYWORD: RouteConfig(
        models=("google/gemini-3.1-flash-lite", "google/gemini-2.5-flash-lite"),
        provider={"require_parameters": True},
        max_tokens=4096,
    ),
}
