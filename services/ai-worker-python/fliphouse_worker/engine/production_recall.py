"""Production recall wiring — phrase-anchored boundaries go LIVE here.

The score stage (``stages/score.py`` → ``StageDeps.score_clips`` →
``_default_score_clips``) builds the cascade and passes it a ``recall_fn``. THIS
module builds that ``recall_fn`` so the phrase-boundary machinery is ACTIVE in
production, not dormant:

    score_handler → _default_score_clips → build_phrase_anchored_recall_fn
        → recall_candidates(align_fn=<RapidFuzz>, punct_fn=None, word_segments=…)
            → phrase_boundaries(h, words, align_fn=…)   ← the END anchors here

``recall_candidates`` asks the LLM for highlights whose ``end_phrase`` is the LAST
WORDS of a COMPLETE sentence; the injected RapidFuzz ``align_fn`` resolves that
verbatim phrase to its word-timestamps so the clip END lands on the finished
thought. ``refine_boundaries`` then only pads/clamps (MIN/MAX/extend caps intact),
and when no phrase resolves it fails open to the existing float→forward-extend path.

``punct_fn`` is INTENTIONALLY ``None`` (no separate RU punctuation-restoration
model): GigaAM-v3 ``e2e_rnnt`` already emits PUNCTUATED segment text, which
``transcription/normalize.py`` projects onto the per-word stream as native
``sent_end`` signals (TRANS-1). So the sentence-end source IS the model's own
punctuation — a bolt-on restorer would be redundant AND would pull model weights
into the pure worker package (breaking the 100%-coverage / no-optional-import
invariant). The pause/discourse heuristic in ``punctuation.py`` remains only as the
license-clean FALLBACK for words a provider left un-punctuated.

This factory is deliberately a PURE, dependency-injected builder (the heavy
``OpenRouterAdapter`` is supplied as ``llm_fn``/``highlight_fn`` by the caller) so
the integration test can drive the EXACT recall closure production runs with fakes,
and assert the wiring is live — it fails if anyone reverts ``align_fn`` to ``None``.
"""

from __future__ import annotations

from collections.abc import Sequence

from .align import AlignFn
from .align_rapidfuzz import align_fn as _rapidfuzz_align_fn
from .highlights import HighlightFn, LLMFn
from .recall import CandidateClip, recall_candidates


def build_phrase_anchored_recall_fn(
    *,
    llm_fn: LLMFn,
    highlight_fn: HighlightFn | None = None,
    word_segments: Sequence[dict] = (),
    align_fn: AlignFn | None = _rapidfuzz_align_fn,
):
    """Build the production ``recall_fn`` with phrase-anchoring WIRED.

    Returns ``recall_fn(transcript, signals) -> tuple[CandidateClip, ...]`` — the exact
    callable the cascade invokes. ``align_fn`` (RapidFuzz, ACTIVE by default) anchors a
    clip's bounds to the LLM's verbatim complete-sentence phrases so the END lands on a
    finished thought; it is injectable so the integration test can drive the real closure
    and FAIL if anyone reverts the wiring to ``None``.
    """

    def recall_fn(transcript: dict, signals: object) -> tuple[CandidateClip, ...]:
        return recall_candidates(
            transcript,
            signals,  # type: ignore[arg-type]
            llm_fn=llm_fn,
            highlight_fn=highlight_fn,
            word_segments=word_segments,
            align_fn=align_fn,
        )

    return recall_fn
