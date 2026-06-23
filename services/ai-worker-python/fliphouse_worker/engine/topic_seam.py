"""Topic-coherence break seam for the linear segmenter (REFRAME Phase 3, item 2).

GOAL: each candidate window should cover ONE topic so the clip feels whole — a
window that drifts across a topic change reads as two half-thoughts stitched
together. TextTiling detects a topic seam by a DIP in lexical/semantic similarity
across a moving boundary; the intended signal here is a multilingual-e5 sentence
embedding (``intfloat/multilingual-e5-*``, **MIT** — explicitly NOT an
English-only model, which would mis-segment RU) cosine dip between the run so far
and the next segment.

STATUS — STUBBED THIS INCREMENT (deliberate, per the phase brief). The embedding
model is a multi-hundred-MB download that cannot run inside the worker package's
CPU-only 100%-coverage gate, and the punctuation+discourse boundary fix (item 1)
is the higher-leverage change for the founder's "clips end mid-thought" complaint.
So this module ships a CLEAN, INJECTABLE seam with an inert default rather than a
half-wired model: ``topic_break_signal`` is a pure function returning ``False``
(no extra break) until a real embedder is provided.

WIRING CONTRACT (so turning it on is a localized change, not a refactor):
``TopicBreakFn(run_text, next_text) -> bool`` returns True when ``next_text`` opens
a new topic and the run should be FLUSHED before it. ``segmenter._should_break``
already breaks on gap/duration; this adds an OR-ed semantic break. The default
``no_topic_break`` keeps current behavior byte-for-byte. A future real
implementation loads ``intfloat/multilingual-e5-base`` once, embeds both texts,
and returns ``cosine(run, next) < TOPIC_SIM_FLOOR``.
"""

from __future__ import annotations

from collections.abc import Callable

# A real e5 embedder would break when run/next cosine similarity drops below this.
# Kept here so the threshold lives with the seam (env-overridable when wired live).
TOPIC_SIM_FLOOR = 0.55

# ``(run_text, next_text) -> should_break_before_next``.
TopicBreakFn = Callable[[str, str], bool]


def no_topic_break(run_text: str, next_text: str) -> bool:
    """Inert default: never forces a topic break (preserves gap/duration-only behavior)."""
    return False
