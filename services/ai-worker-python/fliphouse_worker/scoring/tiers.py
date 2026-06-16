"""Cost/quality tier knob — Бюджет / Баланс / Идеал (P2-S7).

A pure config object that selects how much native-A/V scoring and escalation the
cascade does, mapping the founder's product tiers to engine behavior. Imports
only the pure ``Profile`` StrEnum from llm.routes — no transport, no network.

Tier semantics:
  Бюджет — text-only (av_scope NONE): never cuts video, cheapest GPU+LLM, no escalation.
  Баланс — A/V on the top finalists only (av_scope FINALISTS, ordered by the free
           Stage-A RRF/DSP prior — no extra LLM pre-rank), one escalation on the
           cheaper multimodal route.
  Идеал  — full native A/V on every candidate (av_scope ALL) + escalation to the
           strong route. IDEAL is the default so prior behavior is preserved exactly.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from ..llm.routes import Profile


class AvScope(StrEnum):
    """Which candidates get native A/V scoring in Stage B."""

    NONE = "none"  # text-only, never cut
    FINALISTS = "finalists"  # A/V on the top-N by the free recall prior
    ALL = "all"  # A/V on every candidate


@dataclass(frozen=True)
class TierConfig:
    """A pinned cost/quality profile threaded through the cascade."""

    name: str
    av_scope: AvScope
    escalate: bool
    escalation_profile: Profile | None
    escalation_confidence_floor: int = 70  # confidence < floor → borderline (0-100)
    escalation_gap_epsilon: float = 5.0  # aggregate within eps of the top-k cutoff → borderline
    escalation_max_clips: int = 0  # cap on escalation re-scores per job
    av_finalists_n: int = 5  # FINALISTS: how many top candidates get A/V
    max_score_workers: int = 6  # Stage B concurrency cap


BUDGET = TierConfig(
    name="Бюджет",
    av_scope=AvScope.NONE,
    escalate=False,
    escalation_profile=None,
    escalation_max_clips=0,
)
BALANCE = TierConfig(
    name="Баланс",
    av_scope=AvScope.FINALISTS,
    escalate=True,
    escalation_profile=Profile.SCORING_MULTIMODAL,
    escalation_max_clips=1,
    av_finalists_n=5,
)
IDEAL = TierConfig(
    name="Идеал",
    av_scope=AvScope.ALL,
    escalate=True,
    escalation_profile=Profile.OFFER_MATCH,
    escalation_max_clips=3,
)
