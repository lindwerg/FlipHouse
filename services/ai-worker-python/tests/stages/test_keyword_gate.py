"""P3-A4: the founder env-gate + LLM route/schema contract (network-free)."""

from __future__ import annotations

import pytest

from fliphouse_worker.captioning.keywords import stopword_keyword_selector
from fliphouse_worker.llm.routes import ROUTES, Profile
from fliphouse_worker.llm.schemas import LINE_KEYWORDS_SCHEMA
from fliphouse_worker.stages._types import (
    StageDeps,
    _gemini_keyword_selector,
    resolve_keyword_selector,
)


@pytest.mark.parametrize("flag", ["1", "true", "TRUE", "yes"])
def test_resolve_keyword_selector_enables_gemini_when_flag_truthy(flag: str) -> None:
    assert resolve_keyword_selector({"KEYWORD_LLM_ENABLED": flag}) is _gemini_keyword_selector


@pytest.mark.parametrize("env", [{}, {"KEYWORD_LLM_ENABLED": ""}, {"KEYWORD_LLM_ENABLED": "no"}])
def test_resolve_keyword_selector_defaults_to_pure_heuristic(env: dict) -> None:
    assert resolve_keyword_selector(env) is stopword_keyword_selector


def test_stage_deps_default_keyword_selector_is_the_pure_heuristic() -> None:
    # No network / no env read on ANY default path — the live look is opt-in, not auto-armed.
    assert StageDeps(r2=object()).keyword_selector is stopword_keyword_selector


def test_keyword_route_is_registered_with_strict_json_and_token_budget() -> None:
    route = ROUTES[Profile.KEYWORD]
    assert route.provider == {"require_parameters": True}
    assert all("gemini" in m for m in route.models)
    # max_tokens must clear the 180s worst case (~225 lines * ~14 tok ≈ 3.1k); 4096 has slack.
    assert route.max_tokens is not None and route.max_tokens >= 4096


def test_line_keywords_schema_stays_in_the_gemini_safe_subset() -> None:
    import json

    blob = json.dumps(LINE_KEYWORDS_SCHEMA)
    for banned in ("enum", "minItems", "maxItems", "$ref", "format"):
        assert banned not in blob
    assert LINE_KEYWORDS_SCHEMA["additionalProperties"] is False
    item = LINE_KEYWORDS_SCHEMA["properties"]["lines"]["items"]
    assert item["required"] == ["line", "keyword_index"]


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
