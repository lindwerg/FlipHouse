"""Pure validation of the ``/score`` body → :class:`ScoreRequest`.

Schema-light (no pydantic dependency): ``proxy_url`` must be a non-empty ``https``
string; ``start``/``end``/``sample_fps`` finite numbers with ``end > start`` and
``sample_fps > 0``; ``frames`` a list of lists of ``{x, y, w, h}`` boxes with
non-negative ``w``/``h``. Failure raises :class:`InvalidScoreRequest` (→ 400). The
README notes prod should add SSRF allow-listing on ``proxy_url`` on top of this.
"""

from __future__ import annotations

from .contracts import FaceRef, ScoreRequest
from .errors import InvalidScoreRequest

_HTTPS_SCHEME = "https://"
_NUMERIC = (int, float)


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


def parse_score_request(body: object) -> ScoreRequest:
    """Validate a decoded JSON body and return a frozen :class:`ScoreRequest`."""
    if not isinstance(body, dict):
        raise InvalidScoreRequest("request body must be a JSON object")

    proxy_url = body.get("proxy_url")
    if not isinstance(proxy_url, str) or not proxy_url.strip():
        raise InvalidScoreRequest("missing or empty field: proxy_url")
    if not proxy_url.startswith(_HTTPS_SCHEME):
        raise InvalidScoreRequest("proxy_url must be an https URL")

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
