"""The internal ``clips.json`` contract — written by ``score``, read by ``reframe``.

A Python↔Python intermediate (not in packages/shared): the ranked cascade output
serialized so the reframe stage can rebuild ``SelectedClip`` objects without
re-running the (expensive, networked) cascade. ``dump_clips`` and
``load_selected_clips`` are inverses, kept in one module so the shape can never
drift between the two stages.
"""

from __future__ import annotations

from ..engine.cascade import CascadeResult, SelectedClip
from ..engine.recall import CandidateClip
from ..scoring import ScoredClip

CLIPS_SCHEMA_VERSION = 1


def _candidate_dict(c: CandidateClip) -> dict:
    return {
        "title": c.title,
        "start_time": c.start_time,
        "end_time": c.end_time,
        "llm_score": c.llm_score,
        "dsp_prior": c.dsp_prior,
        "text_excerpt": c.text_excerpt,
    }


def _scored_dict(s: ScoredClip) -> dict:
    return {
        "aggregate": s.aggregate,
        "sub_scores": dict(s.sub_scores),
        "confidence": s.confidence,
        "modalities_used": list(s.modalities_used),
        "model_used": s.model_used,
        "raw_usage": dict(s.raw_usage),
    }


def dump_clips(result: CascadeResult) -> dict:
    """Serialize a CascadeResult to the JSON-safe clips.json payload."""
    return {
        "schema_version": CLIPS_SCHEMA_VERSION,
        "cost_usd_micros": round(result.cost_record.total_usd * 1_000_000),
        "clips": [
            {
                "rank": sel.rank,
                "used_video": sel.used_video,
                "candidate": _candidate_dict(sel.candidate),
                "scored": _scored_dict(sel.scored),
            }
            for sel in result.clips
        ],
    }


def load_selected_clips(payload: dict) -> list[SelectedClip]:
    """Rebuild the ranked ``SelectedClip`` list from a clips.json payload."""
    return [
        SelectedClip(
            candidate=CandidateClip(**clip["candidate"]),
            scored=ScoredClip(**clip["scored"]),
            rank=clip["rank"],
            used_video=clip["used_video"],
        )
        for clip in payload["clips"]
    ]
