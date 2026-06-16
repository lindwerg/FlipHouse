"""Shared fixtures for the per-clip virality scorer tests (P2-S3)."""

import pytest

from fliphouse_worker.llm import openrouter_adapter as ora


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Backoff must never actually sleep during any retry path."""
    monkeypatch.setattr(ora.time, "sleep", lambda _seconds: None)
