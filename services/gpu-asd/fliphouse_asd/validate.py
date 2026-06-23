"""Pure validation of the ``/score`` body → :class:`ScoreRequest`.

Schema-light (no pydantic dependency): ``proxy_url`` must be a non-empty ``https``
string; ``start``/``end``/``sample_fps`` finite numbers with ``end > start`` and
``sample_fps > 0``; ``frames`` a list of lists of ``{x, y, w, h}`` boxes with
non-negative ``w``/``h``. Failure raises :class:`InvalidScoreRequest` (→ 400).

SSRF allow-listing: when ``GPU_ASD_ALLOWED_PROXY_HOSTS`` (comma-separated) is set, any
``proxy_url`` whose hostname is not in the list is rejected — defence against an
attacker steering the GPU fetch at an internal address. When the env is UNSET we keep
the prior https-only behaviour (so dev/tests don't break) but log a warning that the
allowlist is unconfigured. PROD MUST set it to the R2 host that serves the proxies.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from urllib.parse import urlparse

from .contracts import FaceRef, ScoreRequest
from .errors import InvalidScoreRequest

logger = logging.getLogger(__name__)

_HTTPS_SCHEME = "https://"
_NUMERIC = (int, float)

# Comma-separated hostname allowlist for ``proxy_url``. Set this in PROD to the R2 host
# (e.g. ``<bucket>.r2.cloudflarestorage.com``) so the GPU can only fetch proxies from
# the object store, never an internal/metadata address.
ENV_ALLOWED_PROXY_HOSTS = "GPU_ASD_ALLOWED_PROXY_HOSTS"


def _allowed_proxy_hosts(env: Mapping[str, str]) -> frozenset[str]:
    """Parse the comma-separated host allowlist (lower-cased, blanks dropped)."""
    raw = env.get(ENV_ALLOWED_PROXY_HOSTS) or ""
    return frozenset(host.strip().lower() for host in raw.split(",") if host.strip())


def _check_proxy_host(proxy_url: str, env: Mapping[str, str]) -> None:
    """Enforce the SSRF host allowlist when configured; warn (and allow) when not.

    Raises :class:`InvalidScoreRequest` (→ 400) when an allowlist is set and the
    ``proxy_url`` hostname is not on it. When the env is unset, logs a one-line warning
    and lets the request through (https-only fallback), so dev/tests keep working.
    """
    allowed = _allowed_proxy_hosts(env)
    if not allowed:
        logger.warning(
            "%s is unset — proxy_url SSRF allowlist is NOT enforced (https-only). "
            "Set it to the R2 host in production.",
            ENV_ALLOWED_PROXY_HOSTS,
        )
        return
    hostname = (urlparse(proxy_url).hostname or "").lower()
    if hostname not in allowed:
        raise InvalidScoreRequest("proxy_url host is not allow-listed")


def _require_number(body: dict, name: str) -> float:
    value = body.get(name)
    if not isinstance(value, _NUMERIC) or isinstance(value, bool):
        raise InvalidScoreRequest(f"field {name} must be a number")
    return float(value)


def _parse_face(raw: object, frame_idx: int, face_idx: int) -> FaceRef:
    if not isinstance(raw, dict):
        raise InvalidScoreRequest(f"frame {frame_idx} face {face_idx} must be an object")
    coords = []
    for key in ("x", "y", "w", "h"):
        value = raw.get(key)
        if not isinstance(value, _NUMERIC) or isinstance(value, bool):
            raise InvalidScoreRequest(f"frame {frame_idx} face {face_idx} {key} must be a number")
        coords.append(float(value))
    x, y, w, h = coords
    if w < 0.0 or h < 0.0:
        raise InvalidScoreRequest(f"frame {frame_idx} face {face_idx} has negative size")
    return FaceRef(x=x, y=y, w=w, h=h)


def _parse_frames(raw: object) -> tuple[tuple[FaceRef, ...], ...]:
    if not isinstance(raw, list):
        raise InvalidScoreRequest("field frames must be a list")
    frames: list[tuple[FaceRef, ...]] = []
    for i, frame in enumerate(raw):
        if not isinstance(frame, list):
            raise InvalidScoreRequest(f"frame {i} must be a list of faces")
        frames.append(tuple(_parse_face(face, i, j) for j, face in enumerate(frame)))
    return tuple(frames)


def parse_score_request(body: object, *, env: Mapping[str, str] | None = None) -> ScoreRequest:
    """Validate a decoded JSON body and return a frozen :class:`ScoreRequest`.

    ``env`` (defaults to ``os.environ``) supplies the SSRF host allowlist so tests drive
    the set/unset/reject paths with a plain dict — no real process env needed.
    """
    source = os.environ if env is None else env
    if not isinstance(body, dict):
        raise InvalidScoreRequest("request body must be a JSON object")

    proxy_url = body.get("proxy_url")
    if not isinstance(proxy_url, str) or not proxy_url.strip():
        raise InvalidScoreRequest("missing or empty field: proxy_url")
    if not proxy_url.startswith(_HTTPS_SCHEME):
        raise InvalidScoreRequest("proxy_url must be an https URL")
    _check_proxy_host(proxy_url, source)

    start = _require_number(body, "start")
    end = _require_number(body, "end")
    sample_fps = _require_number(body, "sample_fps")
    if end <= start:
        raise InvalidScoreRequest("end must be greater than start")
    if sample_fps <= 0.0:
        raise InvalidScoreRequest("sample_fps must be positive")

    frames = _parse_frames(body.get("frames"))
    return ScoreRequest(
        proxy_url=proxy_url,
        start=start,
        end=end,
        sample_fps=sample_fps,
        frames=frames,
    )
