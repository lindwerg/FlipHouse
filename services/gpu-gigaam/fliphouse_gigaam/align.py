"""P3-A1 — CTC forced-alignment refine pass over the RNN-T word timings.

The boots-on-the-ground ASR (``v3_e2e_rnnt``) emits per-word timestamps from RNN-T
token-emission timing, whose word boundaries DRIFT off the true acoustic onset/offset
by tens-to-hundreds of ms. For a karaoke per-word caption reveal that drift is the
visible substrate UNDER lead (A2) and pop (A3) — so refining it toward the acoustic
boundary is what lands the reveal on the right frame (blueprint A1).

This is a SEAM, exactly like ``transcribe.py``: the REAL CTC pass
(:func:`_default_ctc_align`, GPU + torchaudio + a GigaAM CTC checkpoint) is
``# pragma: no cover`` and only wired when ``ASR_FORCED_ALIGN_ENABLED`` is truthy.

Guarantees (every one proven by a weightless test against an injected fake aligner):

* **Byte-identical when OFF (default).** ``align_fn is None`` → return the SAME
  ``RawPayload`` object — no float churn, no new objects — so the signed callback
  bytes, the R2 ``_raw_gigaam.json``, the worker's ``word_segments``/``cascade``
  contracts, and every caption/scoring golden are untouched.
* **Time-only.** Refinement rebuilds ONLY ``Word.start``/``Word.end``. Word
  text/order/count, ``Segment.start``/``end``/``text`` and ``RawPayload``
  ``duration``/``language`` are never read for mutation — so ``cascade_transcript``
  (the scoring contract) is byte-identical even with alignment ON. (The boundary
  snapper does consume word END times via ``word_segments`` on the worker, so ON can
  shift clip selection — that is a deliberate, live-gated effect, validated OFF-vs-ON
  before the env flip, never a silent contract break.)
* **Fail-open, per segment.** Disabled / no aligner / aligner raises / span-count
  mismatch / non-finite span / wall-budget exhausted → keep the RNN-T times for THAT
  segment; other segments still align. Alignment can only improve or no-op a clip.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from math import isfinite

from .contracts import RawPayload, Segment, Word

ENV_FORCED_ALIGN = "ASR_FORCED_ALIGN_ENABLED"

# Truthy spellings that arm the founder-gated real CTC pass (case-insensitive).
_TRUTHY = frozenset({"1", "true", "yes", "on"})

# Wall-clock ceiling for the WHOLE alignment pass over one source. The real CTC pass is
# a SECOND GPU forward over a source up to 2 h, inside the same Modal job whose only wall
# is ``JOB_TIMEOUT_S=3600`` (modal_app.py). A slow / wedged segment would let Modal
# hard-kill the container mid-pass — which posts NO callback and strands the clip (the
# sibling gpu-asd lane caps its pass for exactly this reason). So once the budget is
# spent we stop aligning and keep RNN-T words for the remaining segments: partial
# progress, never a kill. Sized to leave generous head-room under JOB_TIMEOUT_S.
ALIGN_WALL_BUDGET_S = 600.0

# The GigaAM CTC checkpoint that backs the real aligner. Same v3 family + vocabulary as
# the boots ``v3_e2e_rnnt``, so the token set and per-word count line up (the
# span-count guard below stays reliable). Founder-gated; only loaded by the pragma'd
# real body, never in CI.
_CTC_MODEL_NAME = "v3_ctc"

# (wav_path, segment) -> per-word ABSOLUTE (start, end) seconds, ``len == len(seg.words)``,
# or ``None`` to fail-open THIS segment (keep its RNN-T word times).
CtcAlignFn = Callable[[str, Segment], Sequence[tuple[float, float]] | None]


def forced_align_enabled(env: Mapping[str, str]) -> bool:
    """True iff ``ASR_FORCED_ALIGN_ENABLED`` is a truthy spelling (case-insensitive)."""
    return env.get(ENV_FORCED_ALIGN, "").strip().lower() in _TRUTHY


def resolve_align_fn(env: Mapping[str, str]) -> CtcAlignFn | None:
    """The injected aligner when enabled, else ``None`` (→ identity, byte-identical)."""
    return _default_ctc_align if forced_align_enabled(env) else None


def realign_payload(
    payload: RawPayload,
    wav_path: str,
    *,
    align_fn: CtcAlignFn | None,
    now_fn: Callable[[], float] = time.monotonic,
    budget_s: float = ALIGN_WALL_BUDGET_S,
) -> RawPayload:
    """Refine per-word times via ``align_fn``; identity (same object) when disabled.

    ``align_fn is None`` → return ``payload`` UNCHANGED (the same object — the strongest
    byte-identical guarantee; the clock is never even consulted). Otherwise rebuild each
    segment's words from the aligner, bounded by a wall-clock budget: once ``now_fn()``
    passes the deadline, every remaining segment keeps its RNN-T words. ``Segment``
    start/end/text and ``RawPayload`` duration/language are never touched.
    """
    if align_fn is None:
        return payload  # OFF: identity.

    deadline = now_fn() + budget_s
    segments: list[Segment] = []
    for seg in payload.segments:
        if now_fn() >= deadline:
            segments.append(seg)  # budget spent — keep RNN-T for the rest.
        else:
            segments.append(_realign_segment(seg, wav_path, align_fn))
    return RawPayload(
        duration=payload.duration,
        language=payload.language,
        segments=tuple(segments),
    )


def _realign_segment(seg: Segment, wav_path: str, align_fn: CtcAlignFn) -> Segment:
    """One segment's words re-timed; fail-open to the original segment on any fault."""
    if not seg.words:
        return seg
    try:
        raw_spans = align_fn(wav_path, seg)
    except Exception:  # noqa: BLE001 - any aligner fault keeps the RNN-T times
        return seg
    spans = _sanitize_spans(raw_spans, seg)
    if spans is None:
        return seg
    words = tuple(
        Word(word=w.word, start=s, end=e) for w, (s, e) in zip(seg.words, spans, strict=True)
    )
    return Segment(start=seg.start, end=seg.end, words=words, text=seg.text)


def _sanitize_spans(
    spans: Sequence[tuple[float, float]] | None, seg: Segment
) -> list[tuple[float, float]] | None:
    """Validate + clamp aligner spans to the segment window; ``None`` rejects the segment.

    Rejected (→ keep RNN-T) when ``spans`` is None, its length differs from the word
    count, or any value is non-finite. Otherwise each ``(start, end)`` is clamped into
    ``[seg.start, seg.end]`` (so a refined time can never exceed the segment, hence never
    push the inferred media duration — ``cascade`` stays byte-identical even ON), ``end``
    is lifted to ``start`` when inverted, and starts are forced non-decreasing across the
    segment so the reveal can never run backwards.
    """
    if spans is None or len(spans) != len(seg.words):
        return None
    out: list[tuple[float, float]] = []
    run_max = seg.start
    for raw_start, raw_end in spans:
        start = float(raw_start)
        end = float(raw_end)
        if not (isfinite(start) and isfinite(end)):
            return None
        start = min(max(start, seg.start), seg.end)
        end = min(max(end, seg.start), seg.end)
        if start < run_max:
            start = run_max
        if end < start:
            end = start
        run_max = start
        out.append((start, end))
    return out


_CTC_MODEL = None  # lazily-loaded, per-warm-container CTC model cache.


def _default_ctc_align(  # pragma: no cover - GPU + torchaudio + GigaAM CTC weights
    wav_path: str, seg: Segment
) -> list[tuple[float, float]] | None:
    """REAL forced alignment of one segment's words against its audio span.

    Lazy-imports torch/torchaudio/gigaam (none installed in CI). Loads the GigaAM CTC
    checkpoint once per warm container, slices the waveform to ``[seg.start, seg.end]``,
    runs ``torchaudio.functional.forced_align`` (BSD-2; Viterbi over blank-CTC
    log-probs) against the segment's word tokens, merges sub-word token spans back to one
    ``(start, end)`` per WORD, and offsets frame indices to ABSOLUTE seconds with
    ``seg.start``. Returns one span per word, or ``None`` to fail-open this segment.

    LIVE-CALIBRATION (the one thing no weightless test can pin, hence SHIP-LEAN): the
    emission/log-prob extraction + tokenizer for the GigaAM CTC head and the frame stride
    ``FRAME_SEC`` are confirmed on ``tinkov-plata.mp4`` before the env flip; until then
    this body stays dormant and the caller fails open to RNN-T.
    """
    import gigaam  # type: ignore[import-not-found]
    import torch  # type: ignore[import-not-found]
    import torchaudio  # type: ignore[import-not-found]

    global _CTC_MODEL
    if _CTC_MODEL is None:
        _CTC_MODEL = gigaam.load_model(_CTC_MODEL_NAME)
    model = _CTC_MODEL

    waveform, sample_rate = torchaudio.load(wav_path)
    lo = max(0, int(seg.start * sample_rate))
    hi = max(lo, int(seg.end * sample_rate))
    chunk = waveform[:, lo:hi]
    if chunk.shape[-1] == 0:
        return None

    # Emission log-probs over the segment chunk + the CTC vocab tokenizer are the
    # model-specific bits confirmed at live calibration; the alignment math below is
    # vocabulary-agnostic.
    emission, tokenizer, frame_sec = _ctc_emission(model, chunk, sample_rate)
    tokens = [tokenizer(w.word) for w in seg.words]
    flat = [t for word_tokens in tokens for t in word_tokens]
    if not flat:
        return None
    targets = torch.tensor([flat], dtype=torch.int32, device=emission.device)
    aligned, scores = torchaudio.functional.forced_align(emission, targets, blank=0)
    token_spans = torchaudio.functional.merge_tokens(aligned[0], scores[0])

    spans: list[tuple[float, float]] = []
    cursor = 0
    for word_tokens in tokens:
        n = len(word_tokens)
        if n == 0:
            spans.append((seg.start, seg.start))
            continue
        group = token_spans[cursor : cursor + n]
        cursor += n
        start = seg.start + group[0].start * frame_sec
        end = seg.start + group[-1].end * frame_sec
        spans.append((start, end))
    return spans


def _ctc_emission(model, chunk, sample_rate):  # pragma: no cover - GPU + GigaAM internals
    """Segment chunk → (emission log-probs, word→token-ids tokenizer, FRAME_SEC).

    Isolated so the live-calibration surface (the GigaAM CTC head's emission API +
    tokenizer + subsampling stride) is a single named seam; never runs in CI.
    """
    raise NotImplementedError("GigaAM CTC emission wired at live calibration")


__all__ = [
    "ALIGN_WALL_BUDGET_S",
    "CtcAlignFn",
    "ENV_FORCED_ALIGN",
    "forced_align_enabled",
    "realign_payload",
    "resolve_align_fn",
]
