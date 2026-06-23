"""asd_config — env resolution for the GPU active-speaker lane (REFRAME Phase 4)."""

import math

import pytest

from fliphouse_worker.clipping.asd_config import (
    DEFAULT_CALL_TIMEOUT_S,
    DEFAULT_MIN_FACES,
    MAX_CALL_TIMEOUT_S,
    MAX_RENDER_WORKERS,
    MIN_CALL_TIMEOUT_S,
    MIN_MIN_FACES,
    SAFETY_CAP,
    STAGE_BUDGET_HEADROOM_S,
    STAGE_BUDGET_S,
    AsdConfig,
    assert_stage_budget_invariant,
    load_asd_config,
)

_FULL_ENV = {
    "GPU_ASD_ENABLED": "true",
    "GPU_ASD_ENDPOINT": "https://asd.example",
    "GPU_ASD_SECRET": "shh",
}


def test_enabled_when_flag_truthy_and_fully_configured():
    config = load_asd_config(_FULL_ENV)
    assert config == AsdConfig(
        enabled=True,
        endpoint="https://asd.example",
        secret="shh",
        call_timeout_s=DEFAULT_CALL_TIMEOUT_S,
        min_faces=DEFAULT_MIN_FACES,
    )


def test_disabled_by_default_empty_env():
    config = load_asd_config({})
    assert config.enabled is False
    assert config.endpoint == ""
    assert config.secret == ""


def test_call_timeout_defaults_when_unset():
    assert load_asd_config(_FULL_ENV).call_timeout_s == DEFAULT_CALL_TIMEOUT_S


def test_call_timeout_parsed_from_env():
    config = load_asd_config({**_FULL_ENV, "GPU_ASD_CALL_TIMEOUT_S": "30"})
    assert config.call_timeout_s == 30.0


def test_call_timeout_clamped_to_floor_and_ceiling():
    too_low = load_asd_config({**_FULL_ENV, "GPU_ASD_CALL_TIMEOUT_S": "0.5"})
    too_high = load_asd_config({**_FULL_ENV, "GPU_ASD_CALL_TIMEOUT_S": "9000"})
    assert too_low.call_timeout_s == MIN_CALL_TIMEOUT_S
    assert too_high.call_timeout_s == MAX_CALL_TIMEOUT_S


def test_call_timeout_falls_back_on_junk():
    assert (
        load_asd_config({**_FULL_ENV, "GPU_ASD_CALL_TIMEOUT_S": "not-a-number"}).call_timeout_s
        == DEFAULT_CALL_TIMEOUT_S
    )


def test_call_timeout_falls_back_on_blank():
    assert (
        load_asd_config({**_FULL_ENV, "GPU_ASD_CALL_TIMEOUT_S": "   "}).call_timeout_s
        == DEFAULT_CALL_TIMEOUT_S
    )


def test_min_faces_defaults_when_unset():
    assert load_asd_config(_FULL_ENV).min_faces == DEFAULT_MIN_FACES


def test_min_faces_parsed_from_env():
    assert load_asd_config({**_FULL_ENV, "GPU_ASD_MIN_FACES": "3"}).min_faces == 3


def test_min_faces_floored_at_one():
    assert load_asd_config({**_FULL_ENV, "GPU_ASD_MIN_FACES": "0"}).min_faces == MIN_MIN_FACES


def test_min_faces_falls_back_on_junk():
    assert (
        load_asd_config({**_FULL_ENV, "GPU_ASD_MIN_FACES": "lots"}).min_faces == DEFAULT_MIN_FACES
    )


def test_min_faces_falls_back_on_blank():
    assert load_asd_config({**_FULL_ENV, "GPU_ASD_MIN_FACES": ""}).min_faces == DEFAULT_MIN_FACES


def test_bounds_parsed_even_when_lane_disabled():
    # The cap + gate are always available the moment the lane is flipped on.
    config = load_asd_config({"GPU_ASD_CALL_TIMEOUT_S": "12", "GPU_ASD_MIN_FACES": "4"})
    assert config.enabled is False
    assert config.call_timeout_s == 12.0
    assert config.min_faces == 4


def test_flag_spellings_are_case_insensitive():
    for spelling in ("TRUE", "Yes", "on", "1"):
        env = {**_FULL_ENV, "GPU_ASD_ENABLED": spelling}
        assert load_asd_config(env).enabled is True


def test_unknown_flag_value_is_off():
    assert load_asd_config({**_FULL_ENV, "GPU_ASD_ENABLED": "maybe"}).enabled is False


def test_fails_closed_when_secret_missing():
    env = {"GPU_ASD_ENABLED": "true", "GPU_ASD_ENDPOINT": "https://asd.example"}
    assert load_asd_config(env).enabled is False


def test_fails_closed_when_endpoint_missing():
    env = {"GPU_ASD_ENABLED": "true", "GPU_ASD_SECRET": "shh"}
    assert load_asd_config(env).enabled is False


def test_strips_whitespace_from_endpoint_and_secret():
    env = {
        "GPU_ASD_ENABLED": "true",
        "GPU_ASD_ENDPOINT": "  https://asd.example  ",
        "GPU_ASD_SECRET": " shh ",
    }
    config = load_asd_config(env)
    assert config.endpoint == "https://asd.example"
    assert config.secret == "shh"


def test_call_timeout_ceiling_lowered_to_54():
    # The ceiling was lowered from 120 → 54 so the stage-budget invariant holds (below).
    assert MAX_CALL_TIMEOUT_S == 54.0


def test_stage_budget_constants_are_named():
    # Explicit, named relationship so the invariant can't silently drift.
    assert STAGE_BUDGET_S == 600.0
    assert STAGE_BUDGET_HEADROOM_S == 60.0


def test_cross_service_literals_match_source_of_truth():
    # SAFETY_CAP (cascade.py) and MAX_RENDER_WORKERS (concurrency.py) are imported, not
    # copied, so they track their real definitions automatically.
    from fliphouse_worker.concurrency import MAX_RENDER_WORKERS as REAL_WORKERS
    from fliphouse_worker.engine.cascade import SAFETY_CAP as REAL_CAP

    assert SAFETY_CAP == REAL_CAP == 40
    assert MAX_RENDER_WORKERS == REAL_WORKERS == 4


def test_stage_budget_invariant_holds_at_the_ceiling():
    # The import-time assertion's PASS path: even if every clip burns the full ceiling,
    # the serialized worst case fits the reframe budget minus CPU-render headroom.
    worst_case = math.ceil(SAFETY_CAP / MAX_RENDER_WORKERS) * MAX_CALL_TIMEOUT_S
    budget_for_asd = STAGE_BUDGET_S - STAGE_BUDGET_HEADROOM_S
    assert worst_case <= budget_for_asd
    assert worst_case == 540.0 and budget_for_asd == 540.0


def test_assert_stage_budget_invariant_passes_with_real_constants():
    # Re-invoking with the module defaults is a no-op (the live config holds the bound).
    assert assert_stage_budget_invariant() is None


def test_assert_stage_budget_invariant_raises_when_ceiling_too_high():
    # The FAIL path: a future ceiling bump (e.g. back to 120 s) blows the budget and
    # raises a clear ValueError at import — a loud deploy-time guard, not a render crash.
    with pytest.raises(ValueError, match="stage-budget invariant violated"):
        assert_stage_budget_invariant(call_timeout_s=120.0)
