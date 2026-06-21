"""Pure stage dispatch + fatal/retryable classification for the worker CLI.

The Node BullMQ worker drives each stage via ``python -m fliphouse_worker.cli
<stage>`` and reads a single framed JSON envelope from stdout. The existing ML
core raises plain exceptions and cannot tell the Node side whether a failure is
fatal (don't retry — e.g. OpenRouter 402, bad input) or retryable (429/5xx/I/O).
THIS module is the single authority that makes that distinction, so a 402 fails
the flow at once instead of burning every retry. It is intentionally pure (no
R2/ffmpeg/network) so it is unit-tested to 100%; the impure wiring lives in
``__main__`` (coverage-omitted, integration-only).
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping

# Must match RESULT_FRAME_PREFIX in apps/worker-node/src/python/spawn.ts.
RESULT_FRAME_PREFIX = "@@FLIPHOUSE_RESULT@@"

# A stage handler takes the request dict and returns {"outputs": [...], "metrics": {...}}.
StageHandler = Callable[[dict], dict]

# Render fail-closed exceptions (matched by name to keep this module import-light).
_FATAL_RENDER_NAMES = frozenset(
    {"DimensionMismatchError", "RenderOutputError", "ClipDurationError"}
)
# Transient exceptions safe to retry, matched by NAME so this module imports neither
# openai, botocore, nor subprocess. botocore (EndpointConnectionError /
# ReadTimeoutError / ConnectionClosedError) and subprocess (TimeoutExpired) are NOT
# OSError/TimeoutError subclasses, so without these names they would fall through to
# the UNCAUGHT branch (retryable-by-accident); listing them makes that explicit.
_RETRYABLE_NAMES = frozenset(
    {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "EndpointConnectionError",
        "ReadTimeoutError",
        "ConnectionClosedError",
        "TimeoutExpired",
    }
)


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Map an exception to ``(kind, code)`` where kind is 'fatal' or 'retryable'."""
    name = type(exc).__name__
    message = str(exc)

    if name in _FATAL_RENDER_NAMES:
        return "fatal", name
    if isinstance(exc, ValueError):
        return "fatal", "VALUE_ERROR"
    if isinstance(exc, ImportError):  # incl. ModuleNotFoundError — retrying won't help
        return "fatal", "IMPORT_ERROR"
    if "402" in message or "credits exhausted" in message:
        return "fatal", "OPENROUTER_402"
    if name in _RETRYABLE_NAMES or isinstance(exc, (TimeoutError, ConnectionError, OSError)):
        return "retryable", name
    return "retryable", "UNCAUGHT"


def build_success(outputs: list, metrics: dict) -> dict:
    """Build a success envelope matching the Node StageResult contract.

    The Node side parses ``metrics`` with ``z.record(z.string(), z.number())`` — a
    non-number (str/bool) would fail Node zod AFTER the subprocess already exited
    0, turning a real bug into an inscrutable transport error. This is the single
    chokepoint every handler's result flows through, so validating here rejects a
    bad metric as a ``ValueError`` (→ fatal ``VALUE_ERROR``) at the source.
    """
    for key, value in metrics.items():
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"metric {key!r} must be a number, got {type(value).__name__}")
    return {"ok": True, "outputs": outputs, "metrics": metrics}


def build_failure(kind: str, code: str, message: str) -> dict:
    """Build a failure envelope matching the Node StageResult contract."""
    return {"ok": False, "kind": kind, "code": code, "message": message}


def dispatch(stage: str, request: dict, handlers: Mapping[str, StageHandler]) -> dict:
    """Run one stage's handler and return its result envelope (never raises)."""
    handler = handlers.get(stage)
    if handler is None:
        return build_failure("fatal", "UNKNOWN_STAGE", f"no handler for stage {stage!r}")
    try:
        result = handler(request)
        # build_success validates metrics-are-numbers; keep it INSIDE the try so a
        # bad-metric ValueError is classified (fatal) instead of escaping dispatch.
        return build_success(result.get("outputs", []), result.get("metrics", {}))
    except Exception as exc:  # noqa: BLE001 — boundary: classify everything
        kind, code = classify_exception(exc)
        return build_failure(kind, code, message=str(exc))


def frame_result(result: dict) -> str:
    """Serialize a result envelope as the single framed stdout line the Node side reads."""
    return f"{RESULT_FRAME_PREFIX}{json.dumps(result, separators=(',', ':'))}"
