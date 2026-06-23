"""asd_config — env resolution for the GPU active-speaker lane (REFRAME Phase 4)."""

from fliphouse_worker.clipping.asd_config import AsdConfig, load_asd_config

_FULL_ENV = {
    "GPU_ASD_ENABLED": "true",
    "GPU_ASD_ENDPOINT": "https://asd.example",
    "GPU_ASD_SECRET": "shh",
}


def test_enabled_when_flag_truthy_and_fully_configured():
    config = load_asd_config(_FULL_ENV)
    assert config == AsdConfig(enabled=True, endpoint="https://asd.example", secret="shh")


def test_disabled_by_default_empty_env():
    config = load_asd_config({})
    assert config.enabled is False
    assert config.endpoint == ""
    assert config.secret == ""


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
