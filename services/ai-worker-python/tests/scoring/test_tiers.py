"""Unit coverage for scoring/tiers.py — tier constants and frozen invariants."""

import dataclasses

import pytest

from fliphouse_worker.llm.routes import Profile
from fliphouse_worker.scoring.tiers import BALANCE, BUDGET, IDEAL, AvScope, TierConfig


def test_budget_is_text_only_no_escalation():
    assert BUDGET.av_scope is AvScope.NONE
    assert BUDGET.escalate is False
    assert BUDGET.escalation_profile is None
    assert BUDGET.escalation_max_clips == 0


def test_balance_av_finalists_with_strong_escalation():
    assert BALANCE.av_scope is AvScope.FINALISTS
    assert BALANCE.escalate is True
    assert BALANCE.escalation_profile is Profile.OFFER_MATCH  # contested clip → strong A/V judge
    assert BALANCE.escalation_max_clips == 1
    assert BALANCE.av_finalists_n == 5


def test_ideal_full_av_with_strong_escalation():
    assert IDEAL.av_scope is AvScope.ALL
    assert IDEAL.escalate is True
    assert IDEAL.escalation_profile is Profile.OFFER_MATCH
    assert IDEAL.escalation_max_clips == 3


def test_avscope_string_values():
    assert AvScope.NONE == "none"
    assert AvScope.FINALISTS == "finalists"
    assert AvScope.ALL == "all"


def test_tier_config_is_frozen():
    with pytest.raises(dataclasses.FrozenInstanceError):
        IDEAL.escalation_max_clips = 99  # type: ignore[misc]


def test_tier_config_defaults():
    tier = TierConfig(name="t", av_scope=AvScope.NONE, escalate=False, escalation_profile=None)
    assert tier.escalation_confidence_floor == 70
    assert tier.escalation_gap_epsilon == 5.0
    assert tier.av_finalists_n == 5
    assert tier.max_score_workers == 6
