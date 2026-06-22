"""Environment config + real wiring (founder-gated, ``# pragma: no cover``).

``require_env`` is a tiny PURE helper (unit-tested) that fails fast on a missing
var. ``build_app_from_env`` is the real production wiring — it reads
``GIGAAM_WEBHOOK_SECRET`` and constructs the httpx poster + the real seams; its
body is pragma'd because it pulls live deps (httpx) and is only exercised on the
GPU host, never in CI.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

# The ONE required secret: the HMAC key shared with the webhook-receiver.
ENV_WEBHOOK_SECRET = "GIGAAM_WEBHOOK_SECRET"


def require_env(env: Mapping[str, str], name: str) -> str:
    """Return ``env[name]`` or raise a clear ``KeyError``-style failure."""
    value = env.get(name)
    if not value:
        raise RuntimeError(f"missing required env var: {name}")
    return value


def _httpx_poster():  # pragma: no cover - real network client construction
    """Build the production HTTP poster backed by httpx."""
    import httpx  # type: ignore[import-not-found]

    client = httpx.Client(timeout=30.0)

    def post(url: str, body: bytes, headers: dict[str, str]):
        return client.post(url, content=body, headers=headers)

    return post


def build_app_from_env(env: Mapping[str, str] | None = None):  # pragma: no cover - wiring
    """Construct the real ASGI app from process env (founder-gated live path)."""
    from .app import AppDeps, create_app
    from .orchestrator import TranscribeDeps

    resolved = os.environ if env is None else env
    secret = require_env(resolved, ENV_WEBHOOK_SECRET)
    deps = TranscribeDeps(secret=secret, poster=_httpx_poster())
    return create_app(AppDeps(transcribe=deps))
