"""Unit tests for the worker CLI stderr-logging setup (cli/_logging.py, OBS-1).

Verifies the level resolution from ``FLIPHOUSE_LOG_LEVEL`` and that
``configure_logging`` installs a stderr handler at that level so the engine's
``logger.info`` pipeline-decision lines actually emit (the live container showed
nothing because the root logger defaulted to WARNING).
"""

from __future__ import annotations

import logging

import pytest

from fliphouse_worker.cli import _logging


def test_resolve_log_level_defaults_to_info_when_unset() -> None:
    assert _logging.resolve_log_level({}) == logging.INFO


def test_resolve_log_level_reads_a_named_level_case_insensitively() -> None:
    assert _logging.resolve_log_level({"FLIPHOUSE_LOG_LEVEL": "debug"}) == logging.DEBUG
    assert _logging.resolve_log_level({"FLIPHOUSE_LOG_LEVEL": "WARNING"}) == logging.WARNING


def test_resolve_log_level_falls_back_to_info_on_garbage() -> None:
    # An unknown/typo level must not crash the stage before it can report.
    assert _logging.resolve_log_level({"FLIPHOUSE_LOG_LEVEL": "not-a-level"}) == logging.INFO
    assert _logging.resolve_log_level({"FLIPHOUSE_LOG_LEVEL": "   "}) == logging.INFO


def test_configure_logging_installs_a_stderr_handler_at_the_resolved_level(capsys) -> None:
    # Arrange + Act
    _logging.configure_logging({"FLIPHOUSE_LOG_LEVEL": "INFO"})
    logging.getLogger("fliphouse_worker.test").info("pipeline decision here")

    # Assert: the INFO line reaches stderr (the framed stdout channel stays clean).
    captured = capsys.readouterr()
    assert "pipeline decision here" in captured.err
    assert captured.out == ""


def test_configure_logging_is_idempotent_via_force(capsys) -> None:
    # Re-configuring (e.g. a re-invoked main) must not stack duplicate handlers.
    _logging.configure_logging({})
    _logging.configure_logging({})
    logging.getLogger("fliphouse_worker.test").warning("once")
    captured = capsys.readouterr()
    assert captured.err.count("once") == 1


@pytest.fixture(autouse=True)
def _reset_root_logging():
    """Restore the root logger after each test so handler state never leaks."""
    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level
    yield
    root.handlers[:] = saved_handlers
    root.setLevel(saved_level)


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__]))
