"""Strict JSON schemas for OpenRouter ``response_format`` (doc 04 §2.4).

Schemas are pinned constants so a contract test can catch drift. ``strict: true``
pairs with ``provider.require_parameters: true`` (see :mod:`.routes`).
"""

from __future__ import annotations

from typing import Any

# Virality scoring: a single clip → 0–100 score, hook strength, tags, reason.
# Byte-for-byte the schema from doc 04 §2.4.
VIRALITY_SCORE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "score": {"type": "number"},
        "hook_strength": {"type": "number"},
        "tags": {"type": "array", "items": {"type": "string"}},
        "reason": {"type": "string"},
    },
    "required": ["score", "hook_strength", "tags", "reason"],
    "additionalProperties": False,
}
