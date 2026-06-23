"""Env-driven config for the GPU active-speaker (LR-ASD) lane (REFRAME Phase 4).

PURE + injectable: every reader takes an ``env`` mapping (defaults to
``os.environ``) so the unit suite drives it with a plain dict — no real process env,
no network. Mirrors the GigaAM GPU-ASR seam: a boolean ENABLE flag plus an endpoint
URL and a shared HMAC secret; when the flag is off (the default) the worker uses the
proven CPU YuNet/MediaPipe selector and never touches the network.

Env vars (set on cpu-worker):
  * ``GPU_ASD_ENABLED``  — "true"/"1"/"yes" turns the lane on (default OFF).
  * ``GPU_ASD_ENDPOINT`` — https base URL of the ``services/gpu-asd`` Modal app.
  * ``GPU_ASD_SECRET``   — HMAC-SHA256 key, MUST equal the gpu-asd app's secret.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_ENABLED = "GPU_ASD_ENABLED"
ENV_ENDPOINT = "GPU_ASD_ENDPOINT"
ENV_SECRET = "GPU_ASD_SECRET"

# Accepted truthy spellings for the enable flag (case-insensitive).
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})


@dataclass(frozen=True)
class AsdConfig:
    """Resolved GPU-ASD settings: whether the lane is on + how to reach it."""

    enabled: bool
    endpoint: str
    secret: str


def _is_truthy(value: str | None) -> bool:
    """True when ``value`` is one of the accepted truthy spellings (case-insensitive)."""
    return value is not None and value.strip().lower() in _TRUE_VALUES


def load_asd_config(env: Mapping[str, str] | None = None) -> AsdConfig:
    """Read the GPU-ASD config from ``env`` (defaults to ``os.environ``).

    The lane is treated as ENABLED only when the flag is truthy AND both the endpoint
    and secret are present — a half-configured lane fails CLOSED to ``enabled=False``
    so a missing secret can never silently send unsigned requests or crash the render;
    the worker just uses the CPU selector instead.
    """
    source = os.environ if env is None else env
    endpoint = (source.get(ENV_ENDPOINT) or "").strip()
    secret = (source.get(ENV_SECRET) or "").strip()
    enabled = _is_truthy(source.get(ENV_ENABLED)) and bool(endpoint) and bool(secret)
    return AsdConfig(enabled=enabled, endpoint=endpoint, secret=secret)
