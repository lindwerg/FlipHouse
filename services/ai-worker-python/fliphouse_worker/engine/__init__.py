"""FlipHouse clipping engine — viral highlight selection.

Lifted from SamurAIGPT/AI-Youtube-Shorts-Generator (reference design); the
provider-agnostic highlight selector is kept and the LLM call is injected via
``llm_fn`` (no paid MuAPI / hardcoded Gemini in our tree).
"""

from fliphouse_worker.engine.highlights import (
    dedupe_highlights,
    get_highlights,
    select_highlights,
)

__all__ = ["select_highlights", "get_highlights", "dedupe_highlights"]
