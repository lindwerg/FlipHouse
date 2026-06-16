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
from ..llm.content_parts import DEFAULT_VIDEO_MIME, text_part, video_part
from .aggregate import SCORE_DIMS, aggregate_score
from .prompt import MEDIA_SYSTEM_PROMPT, SYSTEM_PROMPT
from .schema import PER_CLIP_VIRALITY_SCHEMA, SCHEMA_NAME

SCORING_TEMPERATURE = 0.0
_RETRY_NUDGE = (
    "\n\nReturn ONLY a valid JSON object with all 9 keys; visual=-1, audio=-1, "
    'modalities_used=["text"], every score an integer 0-100.'
)
# Media re-ask must NOT force the text-only sentinels: with a real clip attached,
# the text nudge would tell Gemini to drop visual/audio and claim text-only, which
# aggregate.py's dual gate then refuses to count — defeating the A/V path (S6).
_MEDIA_RETRY_NUDGE = (
    "\n\nReturn ONLY a valid JSON object with all 9 keys, every score an integer "
    "0-100, and set modalities_used to reflect what you actually assessed."
)
# Inline base64 video on Gemini-via-OpenRouter must route to Vertex (AI Studio
# rejects inline base64). Merged with the route provider, so require_parameters
# (the strict-JSON guard) survives.
_VERTEX_ONLY = {"only": ["google-vertex"]}


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

    def score_clip(
        self,
        text: str,
        duration_s: float | None = None,
        *,
        video: bytes | None = None,
        video_mime: str = DEFAULT_VIDEO_MIME,
        profile_override: Profile | None = None,
    ) -> ScoredClip:
        is_media = video is not None
        # An escalation overrides ONLY the route (to a stronger tier); the
        # provider_override / system prompt / nudge stay keyed on video presence,
        # so an A/V escalation still pins Vertex + the A/V-activating prompt and
        # routes to the A/V-capable member of the strong route.
        profile = profile_override or (Profile.SCORING_MULTIMODAL if is_media else Profile.SCORING)
        provider_override = _VERTEX_ONLY if is_media else None
        nudge = _MEDIA_RETRY_NUDGE if is_media else _RETRY_NUDGE
        # The text prompt FORBIDS video (visual/audio MUST be -1); the media prompt
        # ACTIVATES A/V (score visual/audio for real). Without this swap the model
        # would dutifully return text-only modalities even with a clip attached.
        system = MEDIA_SYSTEM_PROMPT if is_media else SYSTEM_PROMPT

        def build_user(prompt: str):
            # str on the text path (byte-identical); a fresh content-part list on
            # the media path (video re-attached on every re-ask, never mutated).
            if is_media:
                return [text_part(prompt), video_part(video, mime=video_mime)]
            return prompt

        user = build_user(text)
        last_exc: ValueError | None = None
        for _ in range(self._max_attempts):
            try:
                result = self._adapter.complete_json(
                    profile=profile,
                    system=system,
                    user=user,
                    schema_name=SCHEMA_NAME,
                    schema=PER_CLIP_VIRALITY_SCHEMA,
                    temperature=SCORING_TEMPERATURE,
                    cache_static_prefix=True,
                    provider_override=provider_override,
                )
                data = result.data
                modalities = data.get("modalities_used", [])
                aggregate = aggregate_score(data, modalities, duration_s)
            except ValueError as exc:  # non-JSON (adapter) or rubric-invalid (aggregate)
                last_exc = exc
                user = build_user(text + nudge)
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
