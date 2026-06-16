"""ClipScorer (P2-S3): score one clip's transcript text via the OpenRouter adapter.

Calls the SCORING route at temperature 0 with the strict per-clip schema, then
computes the aggregate in Python. A bounded re-ask handles a model response that
is well-formed JSON but rubric-invalid (the adapter only raises on non-JSON);
it never silently defaults.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

from ..eval import LabeledClip
from ..llm import OpenRouterAdapter, Profile
from .aggregate import SCORE_DIMS, aggregate_score
from .prompt import SYSTEM_PROMPT
from .schema import PER_CLIP_VIRALITY_SCHEMA, SCHEMA_NAME

SCORING_TEMPERATURE = 0.0
_RETRY_NUDGE = (
    "\n\nReturn ONLY a valid JSON object with all 9 keys; visual=-1, audio=-1, "
    'modalities_used=["text"], every score an integer 0-100.'
)


@dataclass(frozen=True)
class ScoredClip:
    aggregate: float
    sub_scores: dict[str, int]
    confidence: int
    modalities_used: list[str]
    model_used: str
    raw_usage: dict[str, Any]


class ClipScorer:
    """Wraps an :class:`OpenRouterAdapter` to score clips against the rubric."""

    def __init__(self, adapter: OpenRouterAdapter, *, max_attempts: int = 2) -> None:
        self._adapter = adapter
        self._max_attempts = max_attempts

    def score_clip(self, text: str, duration_s: float | None = None) -> ScoredClip:
        user = text
        last_exc: ValueError | None = None
        for _ in range(self._max_attempts):
            try:
                result = self._adapter.complete_json(
                    profile=Profile.SCORING,
                    system=SYSTEM_PROMPT,
                    user=user,
                    schema_name=SCHEMA_NAME,
                    schema=PER_CLIP_VIRALITY_SCHEMA,
                    temperature=SCORING_TEMPERATURE,
                    cache_static_prefix=True,
                )
                data = result.data
                modalities = data.get("modalities_used", [])
                aggregate = aggregate_score(data, modalities, duration_s)
            except ValueError as exc:  # non-JSON (adapter) or rubric-invalid (aggregate)
                last_exc = exc
                user = text + _RETRY_NUDGE
                continue
            return ScoredClip(
                aggregate=aggregate,
                sub_scores={d: data[d] for d in SCORE_DIMS},
                confidence=data["confidence"],
                modalities_used=modalities,
                model_used=result.model_used,
                raw_usage=result.raw_usage,
            )
        raise ValueError(f"clip scoring failed after {self._max_attempts} attempts") from last_exc

    def score_clips(self, clips: Sequence[LabeledClip]) -> dict[str, float]:
        """Score each labeled clip's text → {clip_id: aggregate} for the eval-harness."""
        return {clip.clip_id: self.score_clip(clip.text).aggregate for clip in clips}
