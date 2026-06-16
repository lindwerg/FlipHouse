"""Per-clip virality scoring (P2-S3) — rubric, prompt, strict schema, aggregation.

A domain layer parallel to engine/ (highlight selection) and eval/ (the harness),
kept out of llm/ (transport). Text-only stage of the multimodal cascade; the same
schema + aggregation are reused unchanged by the S6 native-A/V stage.
"""

from .aggregate import aggregate_score, length_factor
from .clip_scorer import SCORING_TEMPERATURE, ClipScorer, ScoredClip
from .eval_runner import run_eval
from .prompt import SYSTEM_PROMPT
from .schema import PER_CLIP_VIRALITY_SCHEMA, SCHEMA_NAME

__all__ = [
    "PER_CLIP_VIRALITY_SCHEMA",
    "SCHEMA_NAME",
    "SCORING_TEMPERATURE",
    "SYSTEM_PROMPT",
    "ClipScorer",
    "ScoredClip",
    "aggregate_score",
    "length_factor",
    "run_eval",
]
