"""Unit tests for the stage registry (build_handlers)."""

from __future__ import annotations

import pytest

from fliphouse_worker.cli import _dispatch
from fliphouse_worker.stages import build_handlers
from fliphouse_worker.stages._types import StageDeps

from ._fakes import FakeR2, make_request

_PYTHON_STAGES = {"transcode", "asr", "score", "reframe", "caption", "banner", "store"}


def test_build_handlers_registers_all_seven_python_stages() -> None:
    handlers = build_handlers(StageDeps(r2=FakeR2()))
    assert set(handlers) == _PYTHON_STAGES
    assert all(callable(h) for h in handlers.values())


def test_build_handlers_round_trips_through_dispatch() -> None:
    r2 = FakeR2({"reframe-h0/manifest.json": b'{"clip_count":0,"clips":[]}'})
    handlers = build_handlers(StageDeps(r2=r2))
    req = make_request("store", inputs={"manifest": "reframe-h0/manifest.json"})
    result = _dispatch.dispatch("store", req, handlers)
    assert result["ok"] is True
    assert result["outputs"][0]["key"] == "store-h1/result.json"


def test_build_handlers_default_builds_env_client(monkeypatch: pytest.MonkeyPatch) -> None:
    for name, value in {
        "R2_ACCOUNT_ID": "a",
        "R2_BUCKET": "b",
        "R2_ACCESS_KEY_ID": "k",
        "R2_SECRET_ACCESS_KEY": "s",
    }.items():
        monkeypatch.setenv(name, value)
    handlers = build_handlers()  # no deps → from_env path
    assert set(handlers) == _PYTHON_STAGES


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
