"""FlipHouse clipping engine — viral highlight selection.

Lifted from SamurAIGPT/AI-Youtube-Shorts-Generator (reference design); the
provider-agnostic highlight selector is kept and the LLM call is injected via
``llm_fn`` (no paid MuAPI / hardcoded Gemini in our tree).
"""

from fliphouse_worker.engine.cascade import SelectedClip, select_clips
from fliphouse_worker.engine.highlights import (
    dedupe_highlights,
    get_highlights,
    select_highlights,
)
from fliphouse_worker.engine.recall import CandidateClip, recall_candidates

__all__ = [
    "CandidateClip",
    "SelectedClip",
    "dedupe_highlights",
    "get_highlights",
    "recall_candidates",
    "select_clips",
    "select_highlights",
]
