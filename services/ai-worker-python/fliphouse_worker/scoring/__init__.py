"""Per-clip virality scoring (P2-S3) — rubric, prompt, strict schema, aggregation.

A domain layer parallel to engine/ (highlight selection) and eval/ (the harness),
kept out of llm/ (transport). Text-only stage of the multimodal cascade; the same
schema + aggregation are reused unchanged by the S6 native-A/V stage.
"""

from .aggregate import aggregate_score, length_factor
from .clip_scorer import SCORING_TEMPERATURE, ClipScorer, ScoredClip
from .cost_record import JobCostRecord, ModelSubtotal, summarize_job_cost
from .eval_runner import (
    RATIFIED_MIN_DISPERSION,
    RATIFIED_MIN_DIVERGENCE,
    RATIFIED_MIN_SPEARMAN,
    run_eval,
)
from .pricing import PRICING, PRICING_TABLE_DATE, CallCost, ModelPricing, cost_for_call
from .prompt import MEDIA_SYSTEM_PROMPT, SYSTEM_PROMPT
from .schema import PER_CLIP_VIRALITY_SCHEMA, SCHEMA_NAME
from .tiers import BALANCE, BUDGET, IDEAL, AvScope, TierConfig

__all__ = [
    "BALANCE",
    "BUDGET",
    "IDEAL",
    "MEDIA_SYSTEM_PROMPT",
    "PER_CLIP_VIRALITY_SCHEMA",
    "PRICING",
    "PRICING_TABLE_DATE",
    "RATIFIED_MIN_DISPERSION",
    "RATIFIED_MIN_DIVERGENCE",
    "RATIFIED_MIN_SPEARMAN",
    "SCHEMA_NAME",
    "SCORING_TEMPERATURE",
    "SYSTEM_PROMPT",
    "AvScope",
    "CallCost",
    "ClipScorer",
    "JobCostRecord",
    "ModelPricing",
    "ModelSubtotal",
    "ScoredClip",
    "TierConfig",
    "aggregate_score",
    "cost_for_call",
    "length_factor",
    "run_eval",
    "summarize_job_cost",
]
