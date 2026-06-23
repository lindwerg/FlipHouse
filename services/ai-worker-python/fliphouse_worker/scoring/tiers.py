"""Cost/quality tier knob — Бюджет / Баланс / Идеал (P2-S7).

A pure config object that selects how much native-A/V scoring and escalation the
cascade does, mapping the founder's product tiers to engine behavior. Imports
only the pure ``Profile`` StrEnum from llm.routes — no transport, no network.

Tier semantics (escalation always re-judges a contested clip with full A/V on the
strongest judge — OFFER_MATCH → gemini-2.5-pro on Vertex; tiers differ only in
Stage-B A/V coverage and escalation budget):
  Бюджет — text-only (av_scope NONE): never cuts video, cheapest GPU+LLM, no escalation.
  Баланс — A/V on the top finalists only (av_scope FINALISTS, ordered by the free
           Stage-A RRF/DSP prior — no extra LLM pre-rank), up to 1 escalation.
  Идеал  — full native A/V on every candidate (av_scope ALL) + up to 3 escalations.

``resolve_tier`` reads the ``SCORING_TIER`` env knob (ASK #7): BALANCE is the
default so native A/V lands on the top FINALISTS only, NOT every candidate (IDEAL
= 100+ video calls = too expensive). IDEAL is NO LONGER the implicit default — it
must be requested explicitly via ``SCORING_TIER=ideal``. An unknown value raises
(fail-loud) so a typo can never silently fall through to a costly tier.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
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
    escalation_profile=Profile.OFFER_MATCH,  # contested clip → the strong A/V judge
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

# ── env knob (ASK #7): SCORING_TIER → TierConfig, DEFAULT = BALANCE ──────────
ENV_VAR = "SCORING_TIER"
DEFAULT_TIER = BALANCE  # video only to the top FINALISTS by default, never ALL

# Accepts each tier's cyrillic ``.name`` AND an ascii alias, case-insensitively.
_TIERS_BY_KEY: dict[str, TierConfig] = {
    BUDGET.name.casefold(): BUDGET,
    BALANCE.name.casefold(): BALANCE,
    IDEAL.name.casefold(): IDEAL,
    "budget": BUDGET,
    "balance": BALANCE,
    "ideal": IDEAL,
}


def resolve_tier(env: Mapping[str, str] | None = None) -> TierConfig:
    """Map ``SCORING_TIER`` to a TierConfig; blank/unset → BALANCE, unknown → ValueError.

    Pure and injectable: ``env`` defaults to ``os.environ`` but tests pass a dict so
    no real environment is mutated. Never silently falls back to IDEAL — an
    unrecognized value is a loud configuration error, not a costly default.
    """
    source = os.environ if env is None else env
    raw = source.get(ENV_VAR, "").strip()
    if not raw:
        return DEFAULT_TIER
    tier = _TIERS_BY_KEY.get(raw.casefold())
    if tier is None:
        valid = ", ".join(sorted(_TIERS_BY_KEY))
        raise ValueError(f"unknown {ENV_VAR}={raw!r}; valid values: {valid}")
    return tier
