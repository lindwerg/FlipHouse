"""config — require_env pure helper (build_app_from_env is pragma'd wiring)."""

import pytest

from fliphouse_asd.config import ENV_SECRET, require_env


def test_require_env_returns_present_value():
    assert require_env({ENV_SECRET: "shh"}, ENV_SECRET) == "shh"


def test_require_env_raises_on_missing():
    with pytest.raises(RuntimeError, match="GPU_ASD_SECRET"):
        require_env({}, ENV_SECRET)


def test_require_env_raises_on_blank():
    with pytest.raises(RuntimeError, match="missing required"):
        require_env({ENV_SECRET: ""}, ENV_SECRET)
