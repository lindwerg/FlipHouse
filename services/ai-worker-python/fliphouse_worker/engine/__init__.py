"""FlipHouse clipping engine — viral highlight selection.

Lifted from SamurAIGPT/AI-Youtube-Shorts-Generator (reference design); the
provider-agnostic highlight selector is kept and the LLM call is injected via
``llm_fn`` (no paid MuAPI / hardcoded Gemini in our tree).
"""

from fliphouse_worker.engine.align import align_phrase_to_words, phrase_boundaries
from fliphouse_worker.engine.align_rapidfuzz import align_fn
from fliphouse_worker.engine.cascade import (
    DEFAULT_QUALITY_THRESHOLD,
    SAFETY_CAP,
    CascadeResult,
    SelectedClip,
    select_clips,
)
from fliphouse_worker.engine.escalation import borderline_indices, escalate_borderline
from fliphouse_worker.engine.highlights import (
    dedupe_highlights,
    get_highlights,
    select_highlights,
)
from fliphouse_worker.engine.production_recall import build_phrase_anchored_recall_fn
from fliphouse_worker.engine.recall import CandidateClip, recall_candidates
from fliphouse_worker.engine.scoring_fanout import (
    ClipScore,
    DegradationCounts,
    count_degradations,
    score_candidates,
)
from fliphouse_worker.engine.segmenter import linear_segments

__all__ = [
    "DEFAULT_QUALITY_THRESHOLD",
    "SAFETY_CAP",
    "CandidateClip",
    "CascadeResult",
    "ClipScore",
    "DegradationCounts",
    "SelectedClip",
    "align_fn",
    "align_phrase_to_words",
    "borderline_indices",
    "build_phrase_anchored_recall_fn",
    "count_degradations",
    "dedupe_highlights",
    "escalate_borderline",
    "get_highlights",
    "linear_segments",
    "phrase_boundaries",
    "recall_candidates",
    "score_candidates",
    "select_clips",
    "select_highlights",
]
