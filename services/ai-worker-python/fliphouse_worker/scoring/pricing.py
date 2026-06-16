"""Per-model token pricing for per-job cost accounting (P2-S7).

A pure, table-only cost model: tokens × a pinned per-model USD rate. No network,
no llm/ transport imports — mirrors aggregate.py / metrics.py purity so it is
small, exact, and fully unit-testable.

The ``raw_usage`` the adapter returns is a plain OpenAI ``CompletionUsage`` dump
(``prompt_tokens`` / ``completion_tokens`` / ``total_tokens``) — the adapter sends
no ``usage: {include: true}``, so there is no provider-reported ``cost`` field and
no cached/video/audio token buckets to price. The table is therefore the single
source of truth.

``PRICING`` slugs and rates are pinned at build-time and FOUNDER-RATIFIED at the
checkpoint (mirrors the model-slug discipline in llm/routes.py). The dated
``PRICING_TABLE_DATE`` marks the review cadence. The shipped USD numbers are
placeholders pending founder confirmation — see the P2-S7 checkpoint.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

PRICING_TABLE_DATE = "2026-06-16"  # founder ratifies rates at the P2-S7 checkpoint


@dataclass(frozen=True)
class ModelPricing:
    """USD price per 1M tokens, split prompt vs completion."""

    prompt_usd_per_mtok: float
    completion_usd_per_mtok: float


# Keyed by the EXACT slugs pinned in llm/routes.py (every ROUTES member must
# have an entry — enforced by test). June-2026 rates, ordered by tier so the
# cost record reads sanely: flash-lite (Stage A) < flash (Stage B A/V) < pro / gpt-5
# (A/V escalation) < sonnet (frontier). gemini-3.5-flash at 0.30/2.50 matches the
# Идеал ~$3 / 300-min cost narrative. Founder-ratified at the P2-S7 checkpoint.
PRICING: dict[str, ModelPricing] = {
    "google/gemini-3.1-flash-lite": ModelPricing(0.10, 0.40),
    "google/gemini-2.5-flash-lite": ModelPricing(0.10, 0.40),
    "google/gemini-3.5-flash": ModelPricing(0.30, 2.50),
    "google/gemini-2.5-flash": ModelPricing(0.30, 2.50),
    "google/gemini-2.5-pro": ModelPricing(1.25, 10.00),
    "openai/gpt-5": ModelPricing(1.25, 10.00),
    "anthropic/claude-sonnet-4.5": ModelPricing(3.00, 15.00),
}


@dataclass(frozen=True)
class CallCost:
    """One LLM call's cost. ``cost_source`` is 'computed' or 'missing'."""

    usd: float
    cost_source: str
    prompt_tokens: int
    completion_tokens: int


def cost_for_call(
    model_used: str,
    raw_usage: Mapping[str, Any] | None,
    *,
    pricing: Mapping[str, ModelPricing] = PRICING,
) -> CallCost:
    """Price one call from its token usage. Never raises (invariant: fail-closed).

    Returns ``cost_source='missing'`` (usd 0.0) when the model is not in the
    pricing table or ``raw_usage`` is empty/None; tokens are still recorded when
    present so callers can surface volume even for an unpriced call.
    """
    usage = raw_usage or {}
    prompt_tokens = int(usage.get("prompt_tokens", 0))
    completion_tokens = int(usage.get("completion_tokens", 0))
    entry = pricing.get(model_used)
    if entry is None or not raw_usage:
        return CallCost(0.0, "missing", prompt_tokens, completion_tokens)
    usd = (
        prompt_tokens / 1_000_000 * entry.prompt_usd_per_mtok
        + completion_tokens / 1_000_000 * entry.completion_usd_per_mtok
    )
    return CallCost(round(usd, 6), "computed", prompt_tokens, completion_tokens)
