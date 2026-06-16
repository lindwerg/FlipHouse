"""Per-job cost/model accounting (P2-S7).

A pure fold over the clips' per-call usage into one immutable job record: tokens
and USD by model, A/V vs text clip counts, escalation count, and how many calls
could not be priced. No network, no llm/ transport — only the pure pricing table.

``ClipScore`` is imported under TYPE_CHECKING only: the fold reads it by duck
typing (``cs.scored.model_used`` / ``cs.scored.raw_usage`` / ``cs.used_video``),
so there is no runtime import from engine/ and thus no scoring↔engine import cycle.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from types import MappingProxyType
from typing import TYPE_CHECKING, Any

from .pricing import PRICING, ModelPricing, cost_for_call

if TYPE_CHECKING:  # pragma: no cover
    from ..engine.scoring_fanout import ClipScore


@dataclass(frozen=True)
class ModelSubtotal:
    """Per-model rollup across all calls that used that model."""

    calls: int
    prompt_tokens: int
    completion_tokens: int
    usd: float


@dataclass(frozen=True)
class JobCostRecord:
    """Immutable per-job cost summary. Mapping fields are read-only proxies."""

    by_model: Mapping[str, ModelSubtotal]
    total_usd: float
    av_clip_count: int
    text_clip_count: int
    escalation_count: int
    missing_usage_count: int
    cost_source_mix: Mapping[str, int]

    def __post_init__(self) -> None:
        # Wrap dicts in read-only proxies so the frozen guarantee is genuine —
        # frozen blocks rebinding the field, not mutating the dict it points at.
        object.__setattr__(self, "by_model", MappingProxyType(dict(self.by_model)))
        object.__setattr__(self, "cost_source_mix", MappingProxyType(dict(self.cost_source_mix)))


def summarize_job_cost(
    scores: Sequence[ClipScore],
    *,
    escalation_count: int = 0,
    escalated_usages: Sequence[tuple[str, Mapping[str, Any]]] = (),
    pricing: Mapping[str, ModelPricing] = PRICING,
) -> JobCostRecord:
    """Fold every paid call (the clips' own calls UNION escalation calls) into a record.

    ``scores`` is the PRE-escalation snapshot (every original call); A/V vs text
    counts come from it. ``escalated_usages`` adds each escalation call's
    (model, usage) without losing the original — no paid call is dropped.
    """
    by_model: dict[str, dict[str, float]] = {}
    cost_source_mix: dict[str, int] = {}
    total_usd = 0.0
    av_count = text_count = missing_count = 0

    def account(model: str, usage: Mapping[str, Any] | None) -> None:
        nonlocal total_usd, missing_count
        cost = cost_for_call(model, usage, pricing=pricing)
        bucket = by_model.setdefault(model, {"calls": 0, "pt": 0, "ct": 0, "usd": 0.0})
        bucket["calls"] += 1
        bucket["pt"] += cost.prompt_tokens
        bucket["ct"] += cost.completion_tokens
        bucket["usd"] += cost.usd
        total_usd += cost.usd
        cost_source_mix[cost.cost_source] = cost_source_mix.get(cost.cost_source, 0) + 1
        if cost.cost_source == "missing":
            missing_count += 1

    for clip in scores:
        account(clip.scored.model_used, clip.scored.raw_usage)
        if clip.used_video:
            av_count += 1
        else:
            text_count += 1
    for model, usage in escalated_usages:
        account(model, usage)

    subtotals = {
        model: ModelSubtotal(
            calls=int(b["calls"]),
            prompt_tokens=int(b["pt"]),
            completion_tokens=int(b["ct"]),
            usd=round(b["usd"], 6),
        )
        for model, b in by_model.items()
    }
    return JobCostRecord(
        by_model=subtotals,
        total_usd=round(total_usd, 6),
        av_clip_count=av_count,
        text_clip_count=text_count,
        escalation_count=escalation_count,
        missing_usage_count=missing_count,
        cost_source_mix=cost_source_mix,
    )
