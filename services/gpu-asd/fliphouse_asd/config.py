"""Environment config + real wiring (founder-gated, ``# pragma: no cover``).

``require_env`` is a tiny PURE helper (unit-tested) that fails fast on a missing var.
``build_app_from_env`` is the real production wiring — it reads ``GPU_ASD_SECRET``
and constructs the ASGI app around the live LR-ASD scoring seam; its body is pragma'd
because it pulls the GPU model and is only exercised on the Modal host, never in CI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# The ONE required secret: the HMAC key shared with the worker's ASD transport.
ENV_SECRET = "GPU_ASD_SECRET"


def require_env(env: Mapping[str, str], name: str) -> str:
    """Return ``env[name]`` or raise a clear failure."""
    value = env.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def build_app_from_env(score_fn, env: Mapping[str, str] | None = None):  # pragma: no cover - wiring
    """Construct the real ASGI app from process env + the live scoring seam."""
    from .app import AppDeps, create_app

    resolved = os.environ if env is None else env
    secret = require_env(resolved, ENV_SECRET)
    return create_app(AppDeps(secret=secret, score_fn=score_fn))
