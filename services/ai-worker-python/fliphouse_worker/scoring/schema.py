"""Strict JSON schema for per-clip virality scoring (P2-S3).

Sent to Gemini via OpenRouter with ``response_format: json_schema strict:true``.
Built from the proven-safe Gemini-strict subset only (type / properties /
required / additionalProperties:false / integer / string / array+items /
description) — no enum, oneOf/anyOf/allOf, $ref, format, or min/max — so the
provider's strict transform is a no-op and never 400s. Every property is in
``required`` (strict mode). The SAME schema is reused unchanged by the S6
native-A/V stage (visual/audio then carry real 0-100 scores).
"""

from __future__ import annotations

from typing import Any

SCHEMA_NAME = "per_clip_virality"

# Property order is meaningful: "rationale" first → reason-before-score (CoT).
PER_CLIP_VIRALITY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "rationale": {
            "type": "string",
            "description": "Terse 1-2 sentence reasoning written BEFORE the scores (chain-of-thought first): strongest/weakest dimension and viral verdict, from transcript text only.",
        },
        "hook": {
            "type": "integer",
            "description": "0-100 viral strength of the FIRST sentence only (opening ~10-14 words): curiosity gap, number, negation, contradiction, secret, comparison, question, stakes. Highest weight. Use the full range.",
        },
        "emotion": {
            "type": "integer",
            "description": "0-100 arousal of the emotional/controversial/opinionated CONTENT (awe, anger, anxiety, amusement, outrage, strong opinion) - words, not delivery. Use the full range.",
        },
        "payoff": {
            "type": "integer",
            "description": "0-100 does the clip open a gap AND close it within itself, self-contained with no outside context (standalone clarity, quotability). Highest weight alongside hook. Use the full range.",
        },
        "visual": {
            "type": "integer",
            "description": "NOT assessable from text. At the text-only stage emit exactly -1, the canonical 'not assessed from text' value; never 0, never a guess. Exclude 'video' from modalities_used. At the A/V stage this carries a real 0-100 score.",
        },
        "audio": {
            "type": "integer",
            "description": "NOT assessable from text (music, vocal energy, SFX). At the text-only stage emit exactly -1, the canonical 'not assessed from text' value; never 0, never a guess. Exclude 'audio' from modalities_used. At the A/V stage this carries a real 0-100 score.",
        },
        "pacing": {
            "type": "integer",
            "description": "0-100 verbal-rhythm proxy from text only: idea density, filler/dead-air ratio, complete vs broken sentences. Text-assessable (unlike visual/audio). Ignore raw duration. Use the full range.",
        },
        "confidence": {
            "type": "integer",
            "description": "0-100 certainty in this text-only judgment; lower for short, ambiguous, or context-starved snippets. Does not enter the aggregate.",
        },
        "modalities_used": {
            "type": "array",
            "items": {"type": "string"},
            "description": 'Channels actually used. At the text-only stage emit exactly ["text"]; at the A/V stage ["text","video","audio"]. Allowed: text, video, audio. Never include video/audio when scoring from a transcript.',
        },
    },
    "required": [
        "rationale",
        "hook",
        "emotion",
        "payoff",
        "visual",
        "audio",
        "pacing",
        "confidence",
        "modalities_used",
    ],
    "additionalProperties": False,
}
