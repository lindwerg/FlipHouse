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

# Stage A recall: a transcript chunk → a `highlights` array. Top-level object,
# flat items, NO enum/minItems/maxItems/$ref/format — the Gemini-safe subset of
# JSON-Schema (avoids 400 InvalidArgument). Lays exactly onto the engine's
# ``_sanitize_highlights(parsed.get("highlights"))`` consumer.
HIGHLIGHTS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "highlights": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "start_time": {"type": "number"},
                    "end_time": {"type": "number"},
                    # Verbatim phrase anchors — OPTIONAL (not in ``required``) so a
                    # model that omits them still validates and falls back to the
                    # float locator; keeps the dormant path fail-open. Plain strings
                    # stay inside the Gemini-safe subset (no enum/format).
                    "start_phrase": {"type": "string"},
                    "end_phrase": {"type": "string"},
                    "score": {"type": "integer"},
                    "hook_sentence": {"type": "string"},
                    "virality_reason": {"type": "string"},
                },
                "required": [
                    "title",
                    "start_time",
                    "end_time",
                    "score",
                    "hook_sentence",
                    "virality_reason",
                ],
                "additionalProperties": False,
            },
        }
    },
    "required": ["highlights"],
    "additionalProperties": False,
}

# P3-A4 keyword salience: one {line, keyword_index} row per caption line
# (keyword_index = -1 for no keyword). Gemini-safe subset — NO enum/minItems/maxItems/
# $ref/format (those 400 InvalidArgument). Consumed by keywords.parse_keyword_response,
# which never trusts the values (global out-of-range/duplicate reject + per-row clamp).
LINE_KEYWORDS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "lines": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "line": {"type": "integer"},
                    "keyword_index": {"type": "integer"},
                },
                "required": ["line", "keyword_index"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["lines"],
    "additionalProperties": False,
}
