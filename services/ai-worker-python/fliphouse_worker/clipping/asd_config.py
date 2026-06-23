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
  * ``GPU_ASD_CALL_TIMEOUT_S`` — HARD per-clip wall-clock cap on a single GPU call
    (default 45, clamped to [5, 54]). On timeout the selector fails OPEN to the CPU
    path, so a slow/cold Modal container can NEVER blow the reframe stage budget.
  * ``GPU_ASD_MIN_FACES`` — minimum co-present face count in a clip before the GPU is
    called at all (default 2, floor 1). Single-face clips skip the GPU entirely:
    frontal-largest already disambiguates them, so ASD adds nothing there.
"""

from __future__ import annotations

import math
import os
from collections.abc import Mapping
from dataclasses import dataclass

ENV_ENABLED = "GPU_ASD_ENABLED"
ENV_ENDPOINT = "GPU_ASD_ENDPOINT"
ENV_SECRET = "GPU_ASD_SECRET"
ENV_CALL_TIMEOUT = "GPU_ASD_CALL_TIMEOUT_S"
ENV_MIN_FACES = "GPU_ASD_MIN_FACES"

# Accepted truthy spellings for the enable flag (case-insensitive).
_TRUE_VALUES = frozenset({"1", "true", "yes", "on"})

# ── Per-clip stage-budget invariant (PROVABLY enforced at import) ─────────────
# The Node ``reframe`` stage gives the whole render a hard wall (STAGE_BUDGET_S);
# GPU-ASD per-clip work runs inside it under the bounded encoder fan-out, so the
# worst-case ASD cost is ``ceil(SAFETY_CAP / MAX_RENDER_WORKERS) * call_timeout``.
# We reserve STAGE_BUDGET_HEADROOM_S of that wall for the CPU render itself, and a
# module-level assertion (below) makes the ceiling provably fit so a future bump
# fails LOUD at import (deploy time), not mid-render.
#
# Source of the cross-service literals (kept as a single named relationship so they
# cannot silently drift):
#   * STAGE_BUDGET_S mirrors STAGE_TIMEOUT_MS.reframe = 600_000 ms
#     (apps/worker-node/src/queues/queue-config.ts:70).
#   * SAFETY_CAP / MAX_RENDER_WORKERS are IMPORTED from their real definitions below,
#     so they track the source of truth automatically.
STAGE_BUDGET_S: float = 600.0
STAGE_BUDGET_HEADROOM_S: float = 60.0

# Imported from the real definitions so the invariant can never reference a stale copy:
#   * SAFETY_CAP        — fliphouse_worker/engine/cascade.py:40 (max clips a job emits).
#   * MAX_RENDER_WORKERS — fliphouse_worker/concurrency.py:32 (bounded encoder fan-out).
from ..concurrency import MAX_RENDER_WORKERS  # noqa: E402 — module-level on purpose
from ..engine.cascade import SAFETY_CAP  # noqa: E402 — module-level on purpose

# Per-clip GPU call wall-clock cap. The DEFAULT is conservative; the FLOOR keeps a
# misconfig from starving a real cold-start, and the CEILING is sized so that even the
# worst case ``ceil(SAFETY_CAP / MAX_RENDER_WORKERS) * MAX_CALL_TIMEOUT_S`` stays under
# ``STAGE_BUDGET_S - STAGE_BUDGET_HEADROOM_S`` — the cap is the real safety guarantee,
# proven by the import-time assertion below, not a soft cross-service coupling.
DEFAULT_CALL_TIMEOUT_S: float = 45.0
MIN_CALL_TIMEOUT_S: float = 5.0
MAX_CALL_TIMEOUT_S: float = 54.0


def assert_stage_budget_invariant(
    *,
    safety_cap: int = SAFETY_CAP,
    max_render_workers: int = MAX_RENDER_WORKERS,
    call_timeout_s: float = MAX_CALL_TIMEOUT_S,
    stage_budget_s: float = STAGE_BUDGET_S,
    headroom_s: float = STAGE_BUDGET_HEADROOM_S,
) -> None:
    """Raise if the worst-case serialized GPU-ASD cost can't fit the reframe budget.

    PROVABLE INVARIANT: even if every clip burns the full wall-clock CEILING, the
    serialized worst case ``ceil(safety_cap / max_render_workers) * call_timeout_s`` must
    stay within ``stage_budget_s - headroom_s``. Called at IMPORT with the real module
    constants so a future ceiling/cap/clip-count bump that breaks the budget fails the
    worker LOUD at deploy, never silently mid-render on a paid job. Parameterised so the
    suite can drive both the holding case and a deliberately violating one.
    """
    worst_case = math.ceil(safety_cap / max_render_workers) * call_timeout_s
    budget_for_asd = stage_budget_s - headroom_s
    if worst_case > budget_for_asd:
        raise ValueError(
            "GPU-ASD stage-budget invariant violated: worst-case ASD cost "
            f"ceil({safety_cap}/{max_render_workers})*{call_timeout_s}s = {worst_case}s "
            f"exceeds the reframe budget minus headroom "
            f"({stage_budget_s}-{headroom_s} = {budget_for_asd}s). "
            "Lower MAX_CALL_TIMEOUT_S, raise MAX_RENDER_WORKERS, or lower SAFETY_CAP."
        )


# Fire the invariant at IMPORT with the real constants — a deploy-time guard, not a
# mid-render surprise. The new 54 s ceiling keeps ceil(40/4)*54 = 540 s ≤ 600-60 = 540 s.
assert_stage_budget_invariant()

# Default co-present-face gate. Floor is 1 (0 would call the GPU on faceless clips,
# which is pointless); the GPU only ever helps when >=2 faces compete for the crop.
DEFAULT_MIN_FACES: int = 2
MIN_MIN_FACES: int = 1


@dataclass(frozen=True)
class AsdConfig:
    """Resolved GPU-ASD settings: whether the lane is on + how to reach + bound it."""

    enabled: bool
    endpoint: str
    secret: str
    call_timeout_s: float
    min_faces: int


def _is_truthy(value: str | None) -> bool:
    """True when ``value`` is one of the accepted truthy spellings (case-insensitive)."""
    return value is not None and value.strip().lower() in _TRUE_VALUES


def _parse_call_timeout(value: str | None) -> float:
    """Parse + CLAMP the per-clip wall-clock cap to ``[MIN, MAX]`` (default on junk).

    A missing, blank, or unparseable value falls back to :data:`DEFAULT_CALL_TIMEOUT_S`
    so a typo can never DISABLE the cap; whatever survives is clamped to the sane band
    so neither a too-tight nor a too-loose env can defeat the stage-timeout guarantee.
    """
    if value is None or not value.strip():
        return DEFAULT_CALL_TIMEOUT_S
    try:
        parsed = float(value.strip())
    except ValueError:
        return DEFAULT_CALL_TIMEOUT_S
    return min(MAX_CALL_TIMEOUT_S, max(MIN_CALL_TIMEOUT_S, parsed))


def _parse_min_faces(value: str | None) -> int:
    """Parse + floor the co-present-face gate to ``>= MIN_MIN_FACES`` (default on junk)."""
    if value is None or not value.strip():
        return DEFAULT_MIN_FACES
    try:
        parsed = int(value.strip())
    except ValueError:
        return DEFAULT_MIN_FACES
    return max(MIN_MIN_FACES, parsed)


def load_asd_config(env: Mapping[str, str] | None = None) -> AsdConfig:
    """Read the GPU-ASD config from ``env`` (defaults to ``os.environ``).

    The lane is treated as ENABLED only when the flag is truthy AND both the endpoint
    and secret are present — a half-configured lane fails CLOSED to ``enabled=False``
    so a missing secret can never silently send unsigned requests or crash the render;
    the worker just uses the CPU selector instead.

    ``call_timeout_s`` and ``min_faces`` are ALWAYS parsed (clamped to safe bands) so
    they are available the moment the lane is flipped on — they bound the GPU call so it
    can never blow the reframe stage timeout, and gate it to multi-face clips.
    """
    source = os.environ if env is None else env
    endpoint = (source.get(ENV_ENDPOINT) or "").strip()
    secret = (source.get(ENV_SECRET) or "").strip()
    enabled = _is_truthy(source.get(ENV_ENABLED)) and bool(endpoint) and bool(secret)
    return AsdConfig(
        enabled=enabled,
        endpoint=endpoint,
        secret=secret,
        call_timeout_s=_parse_call_timeout(source.get(ENV_CALL_TIMEOUT)),
        min_faces=_parse_min_faces(source.get(ENV_MIN_FACES)),
    )
