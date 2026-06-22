"""Pure validation of the ``/transcribe`` body → :class:`SubmitRequest`.

Schema-light (no pydantic dependency in the skeleton): every field is required
and must be a non-empty string; ``audio_url``/``webhook_url`` must be ``https``.
Failure raises :class:`InvalidSubmitRequest` (→ 400). README notes that prod
should harden URL allow-listing (SSRF) on top of this.
"""

from __future__ import annotations

from .contracts import SubmitRequest
from .errors import InvalidSubmitRequest

_REQUIRED_FIELDS = ("request_id", "audio_url", "language", "webhook_url", "output_prefix")
_HTTPS_FIELDS = ("audio_url", "webhook_url")
_HTTPS_SCHEME = "https://"


def parse_submit_request(body: object) -> SubmitRequest:
    """Validate a decoded JSON body and return a frozen :class:`SubmitRequest`."""
    if not isinstance(body, dict):
        raise InvalidSubmitRequest("request body must be a JSON object")

    for name in _REQUIRED_FIELDS:
        value = body.get(name)
        if not isinstance(value, str) or not value.strip():
            raise InvalidSubmitRequest(f"missing or empty field: {name}")

    for name in _HTTPS_FIELDS:
        if not body[name].startswith(_HTTPS_SCHEME):
            raise InvalidSubmitRequest(f"{name} must be an https URL")

    return SubmitRequest(
        request_id=body["request_id"],
        audio_url=body["audio_url"],
        language=body["language"],
        webhook_url=body["webhook_url"],
        output_prefix=body["output_prefix"],
    )
