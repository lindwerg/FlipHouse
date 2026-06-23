"""Named errors for the LR-ASD GPU active-speaker service.

Every failure path raises one of these so callers (and the app's 4xx mapping) can
discriminate by type rather than by message string.
"""

from __future__ import annotations


class AsdError(Exception):
    """Base class for every error this service raises."""


class InvalidScoreRequest(AsdError):
    """The ``/score`` body is missing a field or carries a bad value (→ 400)."""


class BadSignature(AsdError):
    """The HMAC signature / timestamp header failed verification (→ 401)."""


class ScoringError(AsdError):
    """The LR-ASD model seam failed to produce a score grid (→ 500)."""
