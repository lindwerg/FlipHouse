"""Config tests — only the pure require_env helper (the wiring is pragma'd)."""

from __future__ import annotations

import pytest

from fliphouse_gigaam.config import ENV_WEBHOOK_SECRET, require_env


def test_require_env_returns_value():
    assert require_env({ENV_WEBHOOK_SECRET: "shh"}, ENV_WEBHOOK_SECRET) == "shh"


def test_require_env_missing_raises():
    with pytest.raises(RuntimeError) as exc:
        require_env({}, ENV_WEBHOOK_SECRET)
    assert ENV_WEBHOOK_SECRET in str(exc.value)


def test_require_env_empty_raises():
    with pytest.raises(RuntimeError):
        require_env({ENV_WEBHOOK_SECRET: ""}, ENV_WEBHOOK_SECRET)
