"""Cascade orchestrator (P2-S6): Stage 0 → Stage A recall → Stage B precision.

A thin coordinator that wires the three stages, all dependency-injected (mirrors
the existing ``llm_fn`` seam): ``_signals_fn`` extracts Stage 0 DSP signals,
``recall_fn`` is the (llm_fn-bound) Stage A recall, and ``scorer`` is the Stage B
``ClipScorer``. Stage B (S6) now cuts each candidate to a short WebM clip and
re-scores it with NATIVE A/V (default Ideal tier = gemini-3.5-flash), in parallel
and fail-closed to text-only per clip (``_score_fn`` → ``score_candidates``).
Results sort by the precise aggregate, get a strict final dedupe, then a quality
threshold gate (not a fixed k) emits EVERY clip at/above the bar (cap-bounded).
The threshold stays the PRIMARY gate; a duration-scaled SAFETY FLOOR only rescues
a long video the (unvalidated) threshold would otherwise starve to near-zero clips
— it never truncates clips that legitimately clear the bar.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass, replace

from ..dsp import LocalSignals, extract_local_signals
from ..scoring import ClipScorer, ScoredClip
from ..scoring.cost_record import JobCostRecord, summarize_job_cost
from ..scoring.tiers import IDEAL, TierConfig
from ..scoring.viral_signals import viral_signal
from .constants import SAFETY_CAP
from .escalation import EscalateFn, escalate_borderline
from .recall import CandidateClip
from .scoring_fanout import (
    ClipScore,
    CutFn,
    DegradationCounts,
    count_degradations,
    finalist_cut,
    score_candidates,
)

logger = logging.getLogger(__name__)

FINAL_DEDUPE_OVERLAP = 0.50  # strict overlap suppression at the output boundary
DEFAULT_QUALITY_THRESHOLD = 55.0  # aggregate (0-100) gate: emit EVERY clip at/above this
_AGGREGATE_CEILING = 100.0  # the boosted aggregate can never exceed the 0-100 scale
# SAFETY_CAP is defined in the leaf ``constants`` module (and re-exported here for
# back-compat) so ``clipping/asd_config.py`` can read it without importing this heavy
# module — see constants.py for the circular-import rationale.
FLOOR_SECONDS_PER_CLIP = 360.0  # one safety-floor clip per 6 minutes of source
MIN_FLOOR_CLIPS = 3  # never floor below the founder's minimum (even for a tiny video)

RecallFn = Callable[[dict, LocalSignals], tuple[CandidateClip, ...]]
ScoreFn = Callable[..., list[ClipScore]]


@dataclass(frozen=True)
class SelectedClip:
    """A final ranked clip: its recall candidate, precise Stage B score, rank, modality."""

    candidate: CandidateClip
    scored: ScoredClip
    rank: int
    used_video: bool = True


RerankFn = Callable[[list[SelectedClip]], list[SelectedClip]]


def _no_rerank(survivors: list[SelectedClip]) -> list[SelectedClip]:
    """Default reranker: identity. Production injects an LLM-backed comparative pass."""
    return survivors


@dataclass(frozen=True)
class CascadeResult:
    """The cascade's output: ranked clips, per-job cost record, A/V tally, scene cuts.

    ``scene_cut_times`` are SOURCE-absolute seconds (from ``LocalSignals.scene_cuts``).
    They flow through clips.json to the reframe stage, where they reset the One-Euro
    filter and snap segment boundaries at shot edges — without them that machinery is
    dead (the render defaults ``scene_cut_times`` to an empty tuple).
    """

    clips: tuple[SelectedClip, ...]
    cost_record: JobCostRecord
    degradation: DegradationCounts = DegradationCounts()
    scene_cut_times: tuple[float, ...] = ()


def _scene_cut_times(signals: object) -> tuple[float, ...]:
    """Pull source-absolute cut times from a ``LocalSignals`` (``()`` when absent).

    Defensive at this seam: a stubbed/None signals object (no ``scene_cuts``) yields
    an empty tuple rather than raising, so the cascade degrades to no-snap rather than
    crashing on a partial signal bundle."""
    cuts = getattr(signals, "scene_cuts", ())
    return tuple(c.time_s for c in cuts)


def _final_dedupe(
    clips: list[SelectedClip], overlap: float = FINAL_DEDUPE_OVERLAP
) -> list[SelectedClip]:
    """Drop a clip overlapping >``overlap`` of the SHORTER span with a higher-scoring kept clip.

    The shorter-span denominator suppresses a long clip that fully contains a kept
    short clip (a one-sided ratio would wrongly let the container survive).
    """
    kept: list[SelectedClip] = []
    for clip in clips:
        c = clip.candidate
        span = c.end_time - c.start_time
        clashes = False
        for k in kept:
            kc = k.candidate
            inter = min(c.end_time, kc.end_time) - max(c.start_time, kc.start_time)
            shorter = min(span, kc.end_time - kc.start_time)
            if inter > 0 and inter > overlap * shorter:
                clashes = True
                break
        if not clashes:
            kept.append(clip)
    return kept


def _apply_viral_bonus(scores: list[ClipScore], signals: object) -> list[ClipScore]:
    """Re-rank: fold the deterministic viral-banger bonus into each clip's aggregate.

    The bonus (hook-strength + quotable-line + DSP energy density, all derived
    cheaply with no extra network) nudges the genuinely punchy clips up the ranking
    so the TOP slots are bangers, not near-tied mediocre clips. It is hard-capped
    (``viral_signal`` caps at ``MAX_VIRAL_BONUS``) and the boosted value is clamped
    to ``_AGGREGATE_CEILING``, so a bonus can never swamp the LLM rubric. PURE:
    returns NEW ``ClipScore``/``ScoredClip`` objects, never mutates the inputs. A
    text-only run (None/partial ``signals``) still works — the DSP term reads 0.
    """
    boosted: list[ClipScore] = []
    for cs in scores:
        cand = cs.candidate
        sig = viral_signal(cand.text_excerpt, cand.start_time, cand.end_time, signals)
        new_aggregate = min(_AGGREGATE_CEILING, round(cs.scored.aggregate + sig.bonus, 4))
        new_scored = replace(cs.scored, aggregate=new_aggregate)
        boosted.append(replace(cs, scored=new_scored))
    return boosted


def _selection_floor(transcript: dict, safety_cap: int) -> int:
    """Minimum clips a source's DURATION should yield, capped by ``safety_cap``.

    Duration is the max segment ``end`` (empty/missing → 0.0). One floor clip per
    ``FLOOR_SECONDS_PER_CLIP``, never below ``MIN_FLOOR_CLIPS`` (2h→20, 30min→5, 6min→3).
    """
    segments = transcript.get("segments", ())
    duration_s = max((s["end"] for s in segments), default=0.0)
    scaled = round(duration_s / FLOOR_SECONDS_PER_CLIP)
    return min(safety_cap, max(MIN_FLOOR_CLIPS, scaled))


def select_clips(
    transcript: dict,
    src_path: str,
    *,
    recall_fn: RecallFn,
    scorer: ClipScorer,
    quality_threshold: float = DEFAULT_QUALITY_THRESHOLD,
    safety_cap: int = SAFETY_CAP,
    tier: TierConfig = IDEAL,
    _signals_fn: Callable[[str], LocalSignals] = extract_local_signals,
    _cut_fn: CutFn = finalist_cut,
    _score_fn: ScoreFn = score_candidates,
    _escalate_fn: EscalateFn = escalate_borderline,
    _rerank_fn: RerankFn = _no_rerank,
) -> CascadeResult:
    """Run the full cascade → EVERY clip at/above ``quality_threshold`` + per-job cost record.

    Stage B → sort → escalate borderline → re-sort → strict dedupe → threshold gate.
    Selection is gated by ``quality_threshold`` (the founder's "no fixed count" rule:
    emit every moment that clears the bar), capped at ``safety_cap`` to avoid a
    pathological count. A duration-scaled SAFETY FLOOR (``_selection_floor``) is the
    only override: if FEWER than the floor clear the bar, the top-``floor`` by
    aggregate are taken instead (never the chronological first) so a miscalibrated
    threshold cannot starve a long video. When enough clips clear the bar the floor
    is inert — the threshold stays primary. The threshold-cutoff index (clips >= threshold)
    is fed to escalation as its margin reference so clips straddling the bar still
    get re-judged. The cost record folds the PRE-escalation calls UNION the
    escalation calls, so no paid call is double-counted or lost.

    ``_cut_fn`` defaults to ``finalist_cut`` (the SAFE preset) so the production
    path compresses each finalist clip BELOW the OpenRouter inline cap WITHOUT the
    ``-fs`` truncation that corrupts the container tail and forces the silent
    text fallback ASK #7(b) is fixing. It is threaded into BOTH the Stage B fan-out
    and the borderline escalation, the only two places a finalist clip is cut.
    """
    signals = _signals_fn(src_path)
    scene_cut_times = _scene_cut_times(signals)
    candidates = recall_fn(transcript, signals)
    if not candidates:
        return CascadeResult(
            clips=(), cost_record=summarize_job_cost([]), scene_cut_times=scene_cut_times
        )

    clip_scores = _score_fn(candidates, scorer, src_path, cut_fn=_cut_fn, tier=tier)
    # Founder-visible A/V tally from the PRE-escalation snapshot (mirrors the
    # cost_record fold): how many finalists actually got video vs fell back to text.
    degradation = count_degradations(clip_scores)
    clip_scores.sort(key=lambda cs: cs.scored.aggregate, reverse=True)
    cutoff = sum(1 for cs in clip_scores if cs.scored.aggregate >= quality_threshold)
    escalated, escalation_count, escalated_usages = _escalate_fn(
        clip_scores, scorer, src_path, k=cutoff, tier=tier, cut_fn=_cut_fn
    )
    # Re-rank the field by folding the deterministic viral-banger bonus into each
    # aggregate AFTER escalation (so the strong LLM re-judge lands first, then the
    # banger prior breaks near-ties toward the punchier clip). The boosted aggregate
    # then drives the sort, the dedupe (keeps the higher boosted clip), and the
    # threshold gate — putting bangers in the top slots.
    boosted = _apply_viral_bonus(escalated, signals)
    boosted = sorted(boosted, key=lambda cs: cs.scored.aggregate, reverse=True)

    selected = [
        SelectedClip(candidate=cs.candidate, scored=cs.scored, rank=0, used_video=cs.used_video)
        for cs in boosted
    ]
    deduped = _final_dedupe(selected)  # already sorted desc by aggregate
    floor = _selection_floor(transcript, safety_cap)
    above = [s for s in deduped if s.scored.aggregate >= quality_threshold]
    chosen = above if len(above) >= floor else deduped[:floor]  # floor rescues a starved long video
    survivors = chosen[:safety_cap]
    logger.info(
        "selection: %d clips >= threshold %.0f (floor=%d, cap=%d) → %d published%s",
        len(above),
        quality_threshold,
        floor,
        safety_cap,
        len(survivors),
        "" if len(above) >= floor else " (safety-floor rescue)",
    )
    # FINAL comparative re-rank of the top published slots: the per-clip scorer +
    # viral bonus rank clips in isolation, so a last LLM pass that sees the
    # finalists TOGETHER picks THE banger among near-ties. Membership is already
    # fixed (dedupe/threshold/cap ran); this only reorders, and is fail-open
    # (default identity, and a bad/raising reply leaves the order untouched).
    survivors = _rerank_fn(survivors)
    clips = tuple(
        SelectedClip(candidate=s.candidate, scored=s.scored, rank=i, used_video=s.used_video)
        for i, s in enumerate(survivors)
    )
    cost_record = summarize_job_cost(
        clip_scores, escalation_count=escalation_count, escalated_usages=escalated_usages
    )
    return CascadeResult(
        clips=clips,
        cost_record=cost_record,
        degradation=degradation,
        scene_cut_times=scene_cut_times,
    )
