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
from .align import AlignFn, phrase_boundaries
from .highlights import HighlightFn, LLMFn, get_highlights
from .punctuation import (
    PunctFn,
    annotate_sentence_ends,
    ends_with_terminal_punct,
    starts_discourse,
)
from .punctuation import _norm as _norm_word

RECALL_OVERSAMPLE = 4  # ask the LLM for 4× the target so recall has headroom
SNAP_TOLERANCE_S = 1.5  # snap a boundary to a pause only if within this distance
RECALL_DEDUPE_OVERLAP = 0.70  # relaxed (vs 0.50 precision dedupe) to keep near-dupes alive
RRF_K = 60  # Reciprocal Rank Fusion damping constant (standard default)
HOOK_WINDOW_S = 3.0  # a scene cut this close to the start strengthens the hook

_W_ENERGY = 0.4
_W_CUT = 0.3
_W_FLAG = 0.3

# ── boundary-snapping (refine_boundaries) ──────────────────────────────────
# The LLM's start/end land mid-utterance or in dead air; snap them to the nearest
# natural SPEECH edge so a clip never opens/closes on a clipped word or silence.
GAP_MIN_S = 0.6  # a between-word gap this long marks a real speech stop/resume
MAX_SHIFT_START_S = 1.0  # hook matters most — move the start the least
MAX_SHIFT_END_S = 2.0  # the tail can travel further to a clean sentence stop
# The founder complaint is clips ENDING mid-thought. The END is therefore biased
# FORWARD (asymmetric from the hook-preserving START): it extends ahead to finish
# the current sentence rather than snapping back onto a breath. A forward
# sentence-end up to this far ahead beats any backward / mid-sentence candidate;
# the extension is still capped by MAX_CLIP_S so the clip can never overrun.
MAX_EXTEND_END_S = 5.0
# After the END is anchored (phrase-align OR float→snap), ALWAYS complete the
# thought: scan the word stream FORWARD to the end of the next word that terminates
# a sentence (terminal punctuation OR the restored ``sent_end`` flag) and move the
# END there. This is the c1/c5 fix: when the LLM's verbatim ``end_phrase`` is itself
# mid-sentence, RapidFuzz anchors the END onto that mid-sentence word and the
# gap-keyed ``_pick_end_edge`` extension can't reach a later terminus that has NO
# pause after it (the next word follows immediately). A direct word-scan can. The
# budget is INTENTIONALLY larger than ``MAX_EXTEND_END_S`` — finishing the thought
# matters more than a tight clip — and is still hard-capped by ``MAX_CLIP_S`` and the
# video duration so the clip can never overrun. No terminus in budget → keep the
# anchored end (fail-safe).
SENTENCE_COMPLETE_BUDGET_S = 10.0
MIN_CLIP_S = 15.0  # prompt floor ("15-44 only for a one-liner")
MAX_CLIP_S = 180.0  # == render MAX_CLIP_DURATION_S (Shorts hard cap)
LEAD_PAD_S = 0.08  # tiny breath before speech resumes (avoids a clipped onset)
TRAIL_PAD_S = 0.20  # let the final word fully decay before the cut


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


def _ends_sentence(word: dict) -> bool:
    """True if a word is a restored sentence end.

    Reads the heuristic ``sent_end`` flag set by ``annotate_sentence_ends`` (RU
    ASR rarely punctuates, so this restored flag — not raw punctuation — is the
    real signal); falls back to a terminal-punctuation check for a word that was
    never annotated (e.g. an audio-pause synthetic candidate)."""
    if "sent_end" in word:
        return bool(word["sent_end"])
    return ends_with_terminal_punct(word["word"])


def _flatten_words(word_segments: Sequence[dict], *, punct_fn: PunctFn | None = None) -> list[dict]:
    """Nested doc-01 ``word_segments`` → a flat, sentence-annotated word list.

    Flattens to ``[{word,start,end}]`` then restores a ``sent_end`` per word so the
    snapper can prefer a real sentence boundary even with no punctuation (RU ASR).
    ``punct_fn`` (optional, default ``None`` = today's pause-only heuristic) is the
    injectable RU punctuation-restoration seam forwarded to ``annotate_sentence_ends``;
    when wired, the snapper aims at MODEL-confirmed sentence ends. PURE —
    ``annotate_sentence_ends`` returns new dicts."""
    flat = [w for ws in word_segments for w in ws.get("words", ())]
    return annotate_sentence_ends(flat, punct_fn=punct_fn)


def _gap_candidates(
    words: Sequence[dict],
) -> tuple[list[tuple[float, bool]], list[tuple[float, bool]]]:
    """Between-word gaps ≥ GAP_MIN_S → (resume, stop) candidate lists of (time, is_preferred).

    A STOP candidate's preference flag is the restored sentence-end of the word
    the speech stops on (terminal punctuation, a STOP discourse marker, or a
    fresh-start pause). A RESUME candidate's preference flag is whether the word
    speech resumes on opens a START discourse marker (итак/короче/смотри…) OR a
    new sentence — so a clip START lands on a fresh thought, not mid-phrase."""
    norms = [_norm_word(w["word"]) for w in words]
    resume: list[tuple[float, bool]] = []
    stop: list[tuple[float, bool]] = []
    for i, (a, b) in enumerate(zip(words, words[1:], strict=False)):
        if b["start"] - a["end"] >= GAP_MIN_S:
            stop.append((a["end"], _ends_sentence(a)))  # speech stops at the prior word's end
            resume_fresh = starts_discourse(norms, i + 1) or _ends_sentence(a)
            resume.append((b["start"], resume_fresh))  # speech resumes at the next word's start
    return resume, stop


def _pick_edge(
    candidates: Sequence[tuple[float, bool]], target: float, max_shift: float
) -> float | None:
    """Nearest candidate within ``max_shift`` of ``target``; a sentence-end candidate
    HARD-beats any mid-sentence one (down-weighting mid-sentence cuts).

    Used for the START edge, where the hook matters most and a small symmetric
    shift is correct. The END edge uses ``_pick_end_edge`` (forward-biased)."""
    within = [c for c in candidates if abs(c[0] - target) <= max_shift]
    if not within:
        return None
    sentence_ends = [c for c in within if c[1]]
    pool = sentence_ends or within
    return min(pool, key=lambda c: abs(c[0] - target))[0]


def _stop_windows(
    words: Sequence[dict], pauses: Sequence[Pause]
) -> list[tuple[float, float, bool]]:
    """Speech-stop windows ``(stop, silence_end, is_sentence_end)`` for the END edge.

    A window means "speech stops at ``stop``, stays silent until ``silence_end``,
    and resumes after". ``is_sentence_end`` is the restored sentence-end flag of the
    word speech stops on (terminal punctuation, a STOP discourse marker, or a
    pause-restored boundary). Built from word-gaps (≥ GAP_MIN_S) and audio pauses;
    ``_gap_candidates`` is left untouched (its flat (time, bool) shape is public).
    The silence span lets the END edge tell a backward snap into TRAILING silence
    (fine — trims dead air) from one that would cross spoken words (forbidden —
    truncates the thought)."""
    windows: list[tuple[float, float, bool]] = []
    for a, b in zip(words, words[1:], strict=False):
        if b["start"] - a["end"] >= GAP_MIN_S:
            windows.append((a["end"], b["start"], _ends_sentence(a)))
    for p in pauses:
        windows.append((p.start, p.end, False))
    return windows


def _pick_end_edge(
    windows: Sequence[tuple[float, float, bool]], target: float, ceiling: float
) -> float | None:
    """Forward-biased END selection — extend the tail to FINISH the thought.

    The founder complaint is clips ending mid-sentence. So the END is asymmetric
    from the start:

      1. PREFER the nearest SENTENCE-END stop at or AFTER ``target`` (forward), as
         long as it is within ``MAX_EXTEND_END_S`` ahead and at or below ``ceiling``
         (the MAX_CLIP_S cap). Extending forward completes the sentence — the point.
      2. Otherwise fall back to the nearest stop within ``MAX_SHIFT_END_S`` of
         ``target`` that does NOT truncate the thought. A backward stop is allowed
         only when ``target`` sits in that stop's own TRAILING silence (snapping
         back merely trims dead air); a backward stop with spoken words between it
         and ``target`` would cut the thought short and is rejected. A forward
         sentence-end always beats a backward / mid-sentence candidate.

    Returns the chosen stop time, or ``None`` to keep the (clamped) LLM end."""
    forward_sent_ends = [
        w
        for w in windows
        if w[2] and target <= w[0] <= ceiling and w[0] - target <= MAX_EXTEND_END_S
    ]
    if forward_sent_ends:
        return min(forward_sent_ends, key=lambda w: w[0] - target)[0]  # nearest ahead

    within = [w for w in windows if abs(w[0] - target) <= MAX_SHIFT_END_S]
    # Forward (w[0] >= target) is always fine. A backward stop is safe only when it
    # is itself a SENTENCE END (ending on a finished thought is complete, even if a
    # little trailing speech — the next thought — is dropped) OR the target lies in
    # its trailing silence [stop, silence_end] (snapping back just trims dead air).
    # A backward MID-sentence stop with speech after it would truncate → rejected.
    eligible = [w for w in within if w[0] >= target or w[2] or target <= w[1]]
    if not eligible:
        return None
    sentence_ends = [w for w in eligible if w[2]]
    pool = sentence_ends or eligible
    return min(pool, key=lambda w: abs(w[0] - target))[0]


def _extend_to_sentence_completion(
    end: float, words: Sequence[dict], ceiling: float
) -> float | None:
    """Forward-extend ``end`` to the next word that TERMINATES a sentence. PURE.

    The founder fix for clips that cut MID-THOUGHT: when the anchored END (a phrase
    align, or a snapped float) lands inside a sentence, scan ``words`` FORWARD for the
    first word whose ``sent_end`` is set (terminal punctuation ``.``/``!``/``?``/``…``
    OR the restored pause/discourse flag) and return that word's END time, so the clip
    finishes the thought. This is STRICTLY a word-stream scan — unlike
    ``_pick_end_edge`` it does NOT require a pause AFTER the terminus, so it reaches a
    sentence end whose next word follows immediately (the exact c1/c5 failure).

    Bounded so the clip can never overrun: the terminus word must END within
    ``SENTENCE_COMPLETE_BUDGET_S`` ahead of ``end`` (generous — finishing the thought
    beats tightness) AND at or below ``ceiling`` (the MAX_CLIP_S/duration cap the
    caller computes). Returns the chosen end, or ``None`` when no terminus qualifies
    (fail-safe: keep the anchored end). Only ever moves the END FORWARD.
    """
    best: float | None = None
    for w in words:
        w_end = float(w["end"])
        if w_end < end:
            continue  # only complete FORWARD — never pull the tail back here
        if w_end - end > SENTENCE_COMPLETE_BUDGET_S or w_end > ceiling:
            continue  # out of the generous budget or past the hard cap
        if _ends_sentence(w):
            if best is None or w_end < best:
                best = w_end  # nearest qualifying terminus ahead
    return best


def refine_boundaries(
    start: float,
    end: float,
    words: Sequence[dict],
    pauses: Sequence[Pause],
    duration: float,
) -> tuple[float, float]:
    """Snap ``(start, end)`` to natural speech edges. PURE, fail-open to the LLM bounds.

    Candidates unify word-gaps (≥ GAP_MIN_S, tagged sentence-end) with audio pauses
    (resume=p.end, stop=p.start). The START snaps to a speech-resume minus a tiny
    lead pad (hook intact, small symmetric shift). The END is biased FORWARD: it
    EXTENDS to the nearest sentence-end ahead (within MAX_EXTEND_END_S and the
    MAX_CLIP_S cap) so the final thought completes, and never snaps BACKWARD onto a
    mid-sentence breath that would truncate it. If a snap would push a side past its
    cap or drive the duration outside [MIN_CLIP_S, MAX_CLIP_S], that side reverts to
    the (clamped) LLM bound — preferring to revert the END so the hook is preserved.

    FINALLY — the c1/c5 fix — once a valid END is settled, ALWAYS run a
    SENTENCE-COMPLETION forward-extension (``_extend_to_sentence_completion``): scan
    the word stream forward to the next sentence terminus within
    ``SENTENCE_COMPLETE_BUDGET_S`` and move the END there. This reaches a terminus that
    the gap-keyed snapper above cannot (one whose next word follows with no pause),
    which is exactly how a phrase-anchored END left mid-sentence gets completed. It is
    hard-capped by MAX_CLIP_S and the video duration, and is declined if it would
    break those caps (fail-safe to the still-clean settled END).
    """
    if not words and not pauses:
        return start, end

    resume_c, _ = _gap_candidates(words)
    for p in pauses:
        resume_c.append((p.end, False))

    def _clamp(v: float) -> float:
        return max(0.0, min(v, duration)) if duration > 0 else max(0.0, v)

    r = _pick_edge(resume_c, start, MAX_SHIFT_START_S)
    new_start = _clamp(r - LEAD_PAD_S) if r is not None else _clamp(start)
    # The forward-extension ceiling: never let the (stop + trail pad) push the clip
    # past MAX_CLIP_S from the start it will actually use.
    end_ceiling = new_start + MAX_CLIP_S - TRAIL_PAD_S
    s = _pick_end_edge(_stop_windows(words, pauses), end, end_ceiling)
    new_end = _clamp(s + TRAIL_PAD_S) if s is not None else _clamp(end)
    orig_start, orig_end = _clamp(start), _clamp(end)

    def _ok(a: float, b: float) -> bool:
        return b > a and MIN_CLIP_S <= (b - a) <= MAX_CLIP_S

    if not _ok(new_start, new_end):
        if _ok(new_start, orig_end):  # revert the END first (keep the snapped hook)
            new_end = orig_end
        elif _ok(orig_start, new_end):
            new_start = orig_start
        else:
            new_start, new_end = orig_start, orig_end

    # Sentence completion (always-on): from the settled END, scan FORWARD to the next
    # sentence terminus so a mid-thought cut finishes its thought. Capped by the same
    # MAX_CLIP_S / duration ceiling; only accepted while the clip stays in-band.
    completion_ceiling = min(
        new_start + MAX_CLIP_S - TRAIL_PAD_S, duration if duration > 0 else float("inf")
    )
    completed = _extend_to_sentence_completion(new_end, words, completion_ceiling)
    if completed is not None:
        candidate_end = _clamp(completed + TRAIL_PAD_S)
        if candidate_end > new_end and _ok(new_start, candidate_end):
            new_end = candidate_end
    return new_start, new_end


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
    word_segments: Sequence[dict] = (),
    punct_fn: PunctFn | None = None,
    align_fn: AlignFn | None = None,
    k: int = 3,
) -> tuple[CandidateClip, ...]:
    """Transcript + Stage 0 signals → a wide, snapped, fused, relaxed-deduped candidate set.

    ``highlight_fn`` (optional) routes the highlight calls through the reliable
    strict-JSON seam so a long video's chunks don't silently truncate/fail.
    ``word_segments`` (optional, doc-01 nested shape) feeds boundary-snapping so a
    clip opens/closes on a clean speech edge instead of mid-word.

    ``punct_fn`` (optional, injectable RU punctuation-restoration seam, default
    inert) feeds ``annotate_sentence_ends`` so the snapper aims at model-confirmed
    sentence ends. ``align_fn`` (optional, injectable verbatim-phrase matcher, e.g.
    RapidFuzz, default inert) lets the recall path derive a candidate's pre-refine
    ``(start, end)`` from the timestamps of the matched ``start_phrase``/
    ``end_phrase`` words; ``refine_boundaries`` then only pads/clamps. Both default
    to ``None`` — fail-open to today's float→refine path — so the engine stays PURE
    and the heavy libs live OUTSIDE the worker package.
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

    words = _flatten_words(word_segments, punct_fn=punct_fn)
    items: list[dict] = []
    for h in raw:
        # Prefer phrase-anchored bounds (the dormant LLM path's resilience): when an
        # align_fn resolves the verbatim start/end phrases to word timestamps, refine
        # only pads/clamps. Otherwise fall back to the LLM floats (fail-open).
        anchored = phrase_boundaries(h, words, align_fn=align_fn)
        pre_start, pre_end = (
            anchored if anchored is not None else (float(h["start_time"]), float(h["end_time"]))
        )
        start, end = refine_boundaries(pre_start, pre_end, words, signals.pauses, duration)
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
