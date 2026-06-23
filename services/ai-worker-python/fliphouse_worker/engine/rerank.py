"""Final comparative re-rank pass: which of the top finalists is THE banger (P2).

The per-clip scorer judges each clip in ISOLATION, so two clips can tie on the
aggregate even though a human comparing them side-by-side would instantly pick the
punchier one. This stage closes that gap: it shows the LLM the top-N finalists
TOGETHER and asks "rank these by viral potential", then reorders the finalists by
the returned permutation. Comparative judgment is exactly where the BANGER vs the
merely-good clip separates.

It is the last word on the TOP slots only — the finalists most likely to be
published — and is strictly fail-open: any malformed / partial / network-failed
ranking leaves the existing order untouched (the per-clip aggregate + the viral
bonus already produced a sane ranking). The LLM seam is injected as ``rank_fn``
(an OpenRouter-bound callable), so this module is pure and fully unit-testable
with zero network.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Sequence
from typing import Protocol, TypeVar

# How many top finalists to re-rank. The published clips live here; re-ranking the
# long tail wastes a call and risks reordering clips no one will ever see.
DEFAULT_RERANK_TOP_N = 10
# A finalist's excerpt is trimmed so N clips fit one prompt without blowing context.
_EXCERPT_CHARS = 400

# ``rank_fn`` takes the built prompt and returns the model's raw text reply.
RankFn = Callable[[str], str]


class _RankableCandidate(Protocol):
    text_excerpt: str


class _RankableScore(Protocol):
    aggregate: float


class Rankable(Protocol):
    """The structural shape this stage needs — both ClipScore and SelectedClip fit."""

    @property
    def candidate(self) -> _RankableCandidate: ...

    @property
    def scored(self) -> _RankableScore: ...


_R = TypeVar("_R", bound=Rankable)

RERANK_SYSTEM_PROMPT = """You are FlipHouse's elite short-form virality judge making the FINAL call on which clips get published. You are shown several candidate clips that ALREADY passed scoring — your job is to rank them against EACH OTHER by pure VIRAL POTENTIAL, hardest-hitting first.

Rank a clip HIGHER when it is a BANGER: a stop-scroll HOOK in the first line, HIGH-AROUSAL "разнос"/hot-take energy (a blunt verdict, a takedown, a confession, a shocking number, a fight-starting claim), a polarizing or controversial stance, and a QUOTABLE self-contained payoff. Rank a clip LOWER when it is FLAT: a calm balanced explainer, a hedged "it depends" take, a setup with no landed line, polite agreement, logistics, or a recap. Correctness and politeness are NOT virality — the clip people will argue about and share wins.

You are comparing clips that are already decent, so be decisive: produce a STRICT TOTAL ORDER, no ties. Respond with ONLY a JSON object of the form {"order": [i, j, k, ...]} where each value is the 0-based index of a clip and the list is a permutation of ALL the indices shown, best first. No markdown, no commentary, nothing else."""


def _trim(text: str) -> str:
    """Collapse whitespace and cap a finalist's excerpt so N clips fit one prompt."""
    collapsed = " ".join(text.split())
    return collapsed[:_EXCERPT_CHARS]


def build_rerank_prompt(scores: Sequence[Rankable]) -> str:
    """Render the finalists as an indexed list for the comparative ranking call."""
    lines = [
        f"[{i}] (score {cs.scored.aggregate:.1f}) {_trim(cs.candidate.text_excerpt)}"
        for i, cs in enumerate(scores)
    ]
    return "Rank these clips by viral potential, best first:\n\n" + "\n\n".join(lines)


def parse_rerank_order(raw: str, n: int) -> list[int] | None:
    """Parse the model's ``{"order": [...]}`` into a validated permutation of 0..n-1.

    Returns ``None`` (caller keeps the existing order) on anything malformed: not
    JSON, missing ``order``, wrong length, out-of-range indices, or duplicates. A
    strict permutation is required so the reorder neither drops nor duplicates a
    finalist.
    """
    text = raw.strip()
    text = re.sub(r"^```(?:json)?\s*", "", text)
    text = re.sub(r"\s*```$", "", text)
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    order = data.get("order")
    if not isinstance(order, list) or len(order) != n:
        return None
    if any(isinstance(x, bool) or not isinstance(x, int) for x in order):
        return None
    if sorted(order) != list(range(n)):
        return None
    return order


def rerank_finalists(
    scores: list[_R],
    *,
    rank_fn: RankFn,
    top_n: int = DEFAULT_RERANK_TOP_N,
) -> list[_R]:
    """Comparatively re-rank the top-``top_n`` finalists; fail-open, immutable.

    Slices the top ``top_n`` (the input is assumed already sorted best-first), asks
    ``rank_fn`` for a permutation, and reorders that head by it; the tail is
    untouched and the head's ClipScores are reused verbatim (no scores change —
    only their ORDER). Any failure (a raising ``rank_fn`` or an unparseable reply)
    returns the input list unchanged. Fewer than 2 finalists is a no-op.
    """
    head = scores[:top_n]
    if len(head) < 2:
        return scores
    tail = scores[top_n:]
    prompt = build_rerank_prompt(head)
    try:
        raw = rank_fn(prompt)
    except Exception:
        return scores
    order = parse_rerank_order(raw, len(head))
    if order is None:
        return scores
    reordered = [head[i] for i in order]
    return reordered + tail
