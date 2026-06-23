"""Unit coverage for scoring/tiers.py — tier constants and frozen invariants."""

import dataclasses

import pytest

from fliphouse_worker.llm.routes import Profile
from fliphouse_worker.scoring.tiers import (
    BALANCE,
    BUDGET,
    DEFAULT_TIER,
    IDEAL,
    AvScope,
    TierConfig,
    resolve_tier,
)


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
    assert BALANCE.av_finalists_n == 8


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


# ── resolve_tier (ASK #7): SCORING_TIER env → TierConfig, default BALANCE ──────


def test_resolve_tier_defaults_to_balance_when_unset():
    assert resolve_tier({}) is BALANCE
    assert DEFAULT_TIER is BALANCE


def test_resolve_tier_blank_value_defaults_to_balance():
    assert resolve_tier({"SCORING_TIER": "   "}) is BALANCE


def test_resolve_tier_ascii_aliases():
    assert resolve_tier({"SCORING_TIER": "budget"}) is BUDGET
    assert resolve_tier({"SCORING_TIER": "balance"}) is BALANCE
    assert resolve_tier({"SCORING_TIER": "ideal"}) is IDEAL


def test_resolve_tier_is_case_insensitive():
    assert resolve_tier({"SCORING_TIER": "IDEAL"}) is IDEAL
    assert resolve_tier({"SCORING_TIER": "  Budget  "}) is BUDGET


def test_resolve_tier_accepts_cyrillic_names():
    assert resolve_tier({"SCORING_TIER": "Бюджет"}) is BUDGET
    assert resolve_tier({"SCORING_TIER": "баланс"}) is BALANCE
    assert resolve_tier({"SCORING_TIER": "Идеал"}) is IDEAL


def test_resolve_tier_unknown_raises_value_error():
    with pytest.raises(ValueError, match="unknown SCORING_TIER"):
        resolve_tier({"SCORING_TIER": "turbo"})


def test_resolve_tier_reads_os_environ_by_default(monkeypatch):
    monkeypatch.delenv("SCORING_TIER", raising=False)
    assert resolve_tier() is BALANCE
    monkeypatch.setenv("SCORING_TIER", "ideal")
    assert resolve_tier() is IDEAL
