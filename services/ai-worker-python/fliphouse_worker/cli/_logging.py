"""Stderr logging setup for the worker stage CLI (OBS-1).

Python's root logger defaults to WARNING with only a lastResort stderr handler,
so the engine's ``logger.info`` pipeline-decision lines (clip count, chunk
splitting, A/V finalist scope) never emit and the live container shows nothing
but ``Starting Container``. This module installs a single ``basicConfig`` that:

  * sends EVERY level to ``stderr`` — the framed ``@@FLIPHOUSE_RESULT@@`` stdout
    channel the Node side parses stays clean (all human/library output is stderr
    per the ``__main__`` docstring), and
  * honours ``FLIPHOUSE_LOG_LEVEL`` (default ``INFO``) so an operator can dial it
    to ``DEBUG`` or ``WARNING`` without a redeploy.

Kept OUT of ``__main__.py`` (which is coverage-omitted) so the level-resolution
logic stays unit-tested. ``PYTHONUNBUFFERED=1`` (set in the Dockerfile) is the
complementary half: it makes this stderr stream line-flush so Railway ingests it.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Mapping

DEFAULT_LOG_LEVEL = "INFO"
_LOG_FORMAT = "%(levelname)s %(name)s %(message)s"


def resolve_log_level(env: Mapping[str, str]) -> int:
    """Resolve the numeric logging level from ``FLIPHOUSE_LOG_LEVEL`` (default INFO).

    An unknown/blank name falls back to INFO rather than raising — a typo in the
    env must never crash the stage before it can report anything.
    """
    name = env.get("FLIPHOUSE_LOG_LEVEL", DEFAULT_LOG_LEVEL).strip().upper()
    level = logging.getLevelName(name or DEFAULT_LOG_LEVEL)
    return level if isinstance(level, int) else logging.INFO


def configure_logging(env: Mapping[str, str]) -> None:
    """Install the stderr root handler at the resolved level (idempotent via ``force``)."""
    logging.basicConfig(
        level=resolve_log_level(env),
        stream=sys.stderr,
        format=_LOG_FORMAT,
        force=True,
    )
