"""Stage A — recall (P2-S5): a wide candidate net biased by Stage 0 signals.

The dominant failure mode of a clip engine is losing a true viral moment before
it is ever scored. Stage A fights that: it asks the LLM for ``k * OVERSAMPLE``
highlights with the inner overlap-dedupe DISABLED (``get_highlights(dedupe=
False)``), snaps each candidate's bounds to the nearest dramatic pause, fuses
the LLM score with a DSP prior (energy peaks, scene-cut-near-hook, laughter/
music) via Reciprocal Rank Fusion, then applies a RELAXED 0.70 overlap dedupe so
near-duplicate true positives survive for Stage B to re-score precisely.

RRF is used because the LLM score (0-100) and the DSP prior (0-1) live on
different scales; ranking each independently and summing reciprocals is
scale-invariant, so the prior can never be numerically swamped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..dsp import LocalSignals, Pause
from ..dsp.audio_flags import FLAG_WIN_S
from .highlights import HighlightFn, LLMFn, get_highlights

RECALL_OVERSAMPLE = 4  # ask the LLM for 4× the target so recall has headroom
SNAP_TOLERANCE_S = 1.5  # snap a boundary to a pause only if within this distance
RECALL_DEDUPE_OVERLAP = 0.70  # relaxed (vs 0.50 precision dedupe) to keep near-dupes alive
RRF_K = 60  # Reciprocal Rank Fusion damping constant (standard default)
HOOK_WINDOW_S = 3.0  # a scene cut this close to the start strengthens the hook

_W_ENERGY = 0.4
_W_CUT = 0.3
_W_FLAG = 0.3


@dataclass(frozen=True)
class CandidateClip:
    """A Stage A recall candidate carrying both the LLM score and the DSP prior."""

    title: str
    start_time: float
    end_time: float
    llm_score: float
    dsp_prior: float
    text_excerpt: str


def snap_to_pause(t: float, pauses: Sequence[Pause], tol: float = SNAP_TOLERANCE_S) -> float:
    """Snap ``t`` to the nearest pause midpoint within ``tol`` seconds, else return ``t``."""
    if not pauses:
        return t
    nearest = min(pauses, key=lambda p: abs(p.mid - t))
    return nearest.mid if abs(nearest.mid - t) <= tol else t


def _dist_to_interval(x: float, lo: float, hi: float) -> float:
    if x < lo:
        return lo - x
    if x > hi:
        return x - hi
    return 0.0


def _proximity(targets: Sequence[float], lo: float, hi: float) -> float:
    """1/(1+nearest distance) of any target to [lo, hi]; 0 when there are no targets."""
    if not targets:
        return 0.0
    best = min(_dist_to_interval(x, lo, hi) for x in targets)
    return 1.0 / (1.0 + best)


def dsp_prior_score(start: float, end: float, signals: LocalSignals) -> float:
    """Continuous [0,1] prior fusing energy peaks, hook-adjacent cuts, and event flags."""
    energy_term = _proximity(signals.energy_peaks_s, start, end)
    cut_term = _proximity([c.time_s for c in signals.scene_cuts], start, start + HOOK_WINDOW_S)
    flag_term = max(
        (
            max(f.laughter_conf, f.music_conf, f.applause_conf)
            for f in signals.audio_flags
            if f.t < end and f.t + FLAG_WIN_S > start
        ),
        default=0.0,
    )
    return round(_W_ENERGY * energy_term + _W_CUT * cut_term + _W_FLAG * flag_term, 6)


def rrf_rank(items: list[dict], *, llm_key: str, prior_key: str, k: int = RRF_K) -> list[dict]:
    """Reciprocal Rank Fusion of two per-item scores → items sorted by fused score desc."""
    by_llm = sorted(range(len(items)), key=lambda i: items[i][llm_key], reverse=True)
    by_dsp = sorted(range(len(items)), key=lambda i: items[i][prior_key], reverse=True)
    rank_llm = {idx: pos for pos, idx in enumerate(by_llm)}
    rank_dsp = {idx: pos for pos, idx in enumerate(by_dsp)}
    fused = [
        {**it, "fused": 1.0 / (k + rank_llm[i]) + 1.0 / (k + rank_dsp[i])}
        for i, it in enumerate(items)
    ]
    return sorted(fused, key=lambda x: x["fused"], reverse=True)


def _relaxed_dedupe(items: list[dict], overlap: float = RECALL_DEDUPE_OVERLAP) -> list[dict]:
    """Drop an item overlapping >``overlap`` of the SHORTER span with a higher-ranked kept item.

    The denominator is the shorter of the two spans so a long clip that fully
    contains a kept short clip is suppressed (a one-sided ratio would let it pass).
    """
    kept: list[dict] = []
    for it in items:
        span = it["end_time"] - it["start_time"]
        clashes = False
        for k in kept:
            inter = min(it["end_time"], k["end_time"]) - max(it["start_time"], k["start_time"])
            shorter = min(span, k["end_time"] - k["start_time"])
            if inter > 0 and inter > overlap * shorter:
                clashes = True
                break
        if not clashes:
            kept.append(it)
    return kept


def _excerpt(transcript: dict, start: float, end: float) -> str:
    return " ".join(
        s["text"].strip()
        for s in transcript.get("segments", [])
        if s["end"] > start and s["start"] < end
    )


def recall_candidates(
    transcript: dict,
    signals: LocalSignals,
    *,
    llm_fn: LLMFn,
    highlight_fn: HighlightFn | None = None,
    k: int = 3,
) -> tuple[CandidateClip, ...]:
    """Transcript + Stage 0 signals → a wide, snapped, fused, relaxed-deduped candidate set.

    ``highlight_fn`` (optional) routes the highlight calls through the reliable
    strict-JSON seam so a long video's chunks don't silently truncate/fail.
    """
    if not transcript.get("segments"):
        return ()

    duration = float(transcript.get("duration", 0.0))
    raw = get_highlights(
        transcript,
        num_clips=k * RECALL_OVERSAMPLE,
        llm_fn=llm_fn,
        highlight_fn=highlight_fn,
        dedupe=False,
    )["highlights"]

    items: list[dict] = []
    for h in raw:
        start = snap_to_pause(float(h["start_time"]), signals.pauses)
        end = snap_to_pause(float(h["end_time"]), signals.pauses)
        if duration > 0:
            start, end = min(start, duration), min(end, duration)
        if end <= start:  # snapping collapsed the span — fall back to the LLM bounds
            start, end = float(h["start_time"]), float(h["end_time"])
        items.append(
            {
                "title": h["title"],
                "start_time": start,
                "end_time": end,
                "llm_score": float(h["score"]),
                "dsp_prior": dsp_prior_score(start, end, signals),
                "text_excerpt": _excerpt(transcript, start, end),
            }
        )

    fused = rrf_rank(items, llm_key="llm_score", prior_key="dsp_prior")
    return tuple(
        CandidateClip(
            title=it["title"],
            start_time=it["start_time"],
            end_time=it["end_time"],
            llm_score=it["llm_score"],
            dsp_prior=it["dsp_prior"],
            text_excerpt=it["text_excerpt"],
        )
        for it in _relaxed_dedupe(fused)
    )
