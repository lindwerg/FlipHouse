"""Unit coverage for scoring/pricing.py — table-only cost, never raises."""

import pytest

from fliphouse_worker.llm.routes import ROUTES
from fliphouse_worker.scoring.pricing import (
    PRICING,
    PRICING_TABLE_DATE,
    ModelPricing,
    cost_for_call,
)

_ALL_ROUTE_SLUGS = sorted({slug for route in ROUTES.values() for slug in route.models})


def test_cost_for_call_computed_exact_usd():
    cost = cost_for_call(
        "google/gemini-3.5-flash",
        {"prompt_tokens": 1_000_000, "completion_tokens": 500_000},
    )
    assert cost.cost_source == "computed"
    # 1M prompt @1.50 + 0.5M completion @9.00 = 1.50 + 4.50
    assert cost.usd == pytest.approx(6.0)
    assert cost.prompt_tokens == 1_000_000 and cost.completion_tokens == 500_000


def test_cost_for_call_unknown_slug_is_missing_but_keeps_tokens():
    cost = cost_for_call("acme/unknown-model", {"prompt_tokens": 10, "completion_tokens": 5})
    assert cost.usd == 0.0 and cost.cost_source == "missing"
    assert cost.prompt_tokens == 10 and cost.completion_tokens == 5


def test_cost_for_call_empty_usage_is_missing():
    assert cost_for_call("google/gemini-3.5-flash", {}).cost_source == "missing"
    assert cost_for_call("google/gemini-3.5-flash", {}).usd == 0.0


def test_cost_for_call_none_usage_is_missing_and_never_raises():
    cost = cost_for_call("google/gemini-3.5-flash", None)
    assert cost.usd == 0.0 and cost.cost_source == "missing"
    assert cost.prompt_tokens == 0 and cost.completion_tokens == 0


def test_cost_for_call_missing_token_keys_default_to_zero():
    # raw_usage truthy (has total_tokens) but lacks prompt/completion keys → no KeyError.
    cost = cost_for_call("google/gemini-3.5-flash", {"total_tokens": 7})
    assert cost.cost_source == "computed"
    assert cost.usd == 0.0 and cost.prompt_tokens == 0 and cost.completion_tokens == 0


@pytest.mark.parametrize("slug", _ALL_ROUTE_SLUGS)
def test_every_route_slug_is_priced(slug):
    entry = PRICING[slug]
    assert isinstance(entry, ModelPricing)
    assert entry.prompt_usd_per_mtok > 0 and entry.completion_usd_per_mtok > 0


def test_pricing_table_date_is_iso_string():
    assert isinstance(PRICING_TABLE_DATE, str) and len(PRICING_TABLE_DATE) == 10


def test_custom_pricing_table_is_honored():
    custom = {"x/y": ModelPricing(2.0, 4.0)}
    cost = cost_for_call(
        "x/y", {"prompt_tokens": 1_000_000, "completion_tokens": 0}, pricing=custom
    )
    assert cost.usd == pytest.approx(2.0) and cost.cost_source == "computed"
