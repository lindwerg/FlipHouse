"""Unit tests for the pure stage dispatch + classification (cli/_dispatch.py)."""

from __future__ import annotations

import json

import pytest

from fliphouse_worker.cli import _dispatch as d


class DimensionMismatchError(RuntimeError):
    """Name-matched render fail-closed exception."""


class RateLimitError(Exception):
    """Name-matched transient SDK exception."""


def test_classify_render_fail_closed_is_fatal() -> None:
    kind, code = d.classify_exception(DimensionMismatchError("not 1080x1920"))
    assert kind == "fatal"
    assert code == "DimensionMismatchError"


def test_classify_value_and_import_errors_are_fatal() -> None:
    assert d.classify_exception(ValueError("bad json")) == ("fatal", "VALUE_ERROR")
    assert d.classify_exception(ModuleNotFoundError("libGL")) == ("fatal", "IMPORT_ERROR")


def test_classify_openrouter_402_is_fatal_by_message() -> None:
    assert d.classify_exception(RuntimeError("OpenRouter credits exhausted (402)")) == (
        "fatal",
        "OPENROUTER_402",
    )


def test_classify_transient_by_name_and_stdlib_is_retryable() -> None:
    assert d.classify_exception(RateLimitError("429")) == ("retryable", "RateLimitError")
    assert d.classify_exception(TimeoutError("slow"))[0] == "retryable"
    assert d.classify_exception(OSError("disk"))[0] == "retryable"


def test_classify_generic_runtime_is_retryable_uncaught() -> None:
    assert d.classify_exception(RuntimeError("OpenRouter call failed after retries")) == (
        "retryable",
        "UNCAUGHT",
    )


def test_dispatch_unknown_stage_is_fatal() -> None:
    result = d.dispatch("nope", {}, {})
    assert result == {
        "ok": False,
        "kind": "fatal",
        "code": "UNKNOWN_STAGE",
        "message": "no handler for stage 'nope'",
    }


def test_dispatch_success_wraps_handler_output() -> None:
    handlers = {"transcode": lambda _req: {"outputs": [{"key": "t.json"}], "metrics": {"ms": 5}}}
    result = d.dispatch("transcode", {"stage": "transcode"}, handlers)
    assert result == {"ok": True, "outputs": [{"key": "t.json"}], "metrics": {"ms": 5}}


def test_dispatch_success_defaults_missing_outputs_and_metrics() -> None:
    handlers = {"store": lambda _req: {}}
    assert d.dispatch("store", {}, handlers) == {"ok": True, "outputs": [], "metrics": {}}


def test_dispatch_catches_and_classifies_handler_exception() -> None:
    def boom(_req: dict) -> dict:
        raise RuntimeError("OpenRouter credits exhausted (402)")

    result = d.dispatch("score", {}, {"score": boom})
    assert result["ok"] is False
    assert result["kind"] == "fatal"
    assert result["code"] == "OPENROUTER_402"


def test_frame_result_prefixes_compact_json() -> None:
    line = d.frame_result(d.build_success([], {"ms": 1}))
    assert line.startswith(d.RESULT_FRAME_PREFIX)
    assert json.loads(line[len(d.RESULT_FRAME_PREFIX) :]) == {
        "ok": True,
        "outputs": [],
        "metrics": {"ms": 1},
    }


def test_build_failure_shape() -> None:
    assert d.build_failure("retryable", "X", "y") == {
        "ok": False,
        "kind": "retryable",
        "code": "X",
        "message": "y",
    }


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
