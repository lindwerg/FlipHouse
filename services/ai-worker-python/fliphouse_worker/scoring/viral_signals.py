"""Deterministic viral-banger signals → a bounded ranking bonus (P2 clipping-mvp).

The LLM rubric is the primary judge, but an LLM run at temperature 0 still
compresses scores and can miss the BANGER among near-tied clips. This module adds
a cheap, deterministic, CPU-only PRIOR that nudges the genuinely punchy clips up
the ranking — the founder's "верх должен быть разнос" requirement — WITHOUT
touching the scorer/aggregate contracts. It is a small additive bonus folded into
``ScoredClip.aggregate`` at the cascade boundary (``apply_viral_bonus``), so a
miscalibrated bonus can never dominate the rubric (it is hard-capped) and a
text-only run still works (the DSP terms simply read as 0).

Three signals, all detectable with no network:

* HOOK STRENGTH — lexical scan of the opening words for viral hook patterns
  (a number/stat, negation, secret/insider frame, contradiction, a question, or
  stakes) minus a dead-opener penalty (RU filler like "так, давайте"). The opening
  line is where a clip lives or dies, so this carries the most weight.
* QUOTABLE LINE — does the clip contain a short, punchy, self-contained
  declarative line that would work as a quote-card / screenshot caption?
* ENERGY / LAUGHTER DENSITY — reuse the Stage-0 DSP ``LocalSignals``: loud bursts
  (laughter / shout / beat-drop) and laughter flags landing inside the clip span
  are an emotional-peak proxy the transcript cannot see.

CALIBRATION NOTE (founder labels): ``MAX_VIRAL_BONUS`` and the per-signal weights
are set conservatively from the research (hook dominates, then emotion, then
quotability) but are NOT yet fit to a human-labeled set. They are intentionally a
SMALL fraction of the 0-100 aggregate so they only break near-ties. Once the
founder scores the human eval set, re-fit ``MAX_VIRAL_BONUS`` and the weights so
the bonus-induced re-ranking maximizes rank-correlation, then lock them here.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# A bare-token normalizer kept LOCAL on purpose: ``scoring`` must not import
# ``engine`` (the dependency runs engine→scoring via the cascade; the reverse
# would be a cycle). This mirrors ``engine.punctuation._norm`` for the lexical
# scan — lowercase, strip surrounding/terminal punctuation → a matchable token.
_STRIP_CHARS = ".,!?…:;\"'`()[]{}«»”’-"


def _norm(word: str) -> str:
    """Lowercase, strip surrounding/terminal punctuation → a bare matchable token."""
    return word.strip().lower().strip(_STRIP_CHARS)


# ── tuning constants (calibration pending founder labels — see module docstring) ──
MAX_VIRAL_BONUS = 8.0  # hard cap on the additive bonus (≤ ~8% of the 0-100 aggregate)
_W_HOOK = 0.5  # opening line dominates a short clip's fate
_W_QUOTABLE = 0.2  # a caption-worthy line lifts shareability
_W_ENERGY = 0.3  # emotional-peak proxy the transcript cannot see

# A clip's "opening" is the first few words — the hook lives here.
HOOK_WORD_COUNT = 14  # the prompt's "~10-14 words" opening window

# A quote-card line is short and declarative; too long is a paragraph, not a quote.
QUOTABLE_MIN_WORDS = 3
QUOTABLE_MAX_WORDS = 14

# Energy density saturates: this many in-span emotional-peak events → full credit.
ENERGY_SATURATION_EVENTS = 3
# A laughter flag below this confidence is noise, not a real laugh.
LAUGHTER_FLAG_FLOOR = 0.2

# ── RU viral hook lexicon (lowercased, normalized tokens) ────────────────────
# Negation / "nobody says" framing — the single strongest RU hook family.
_HOOK_NEGATION = frozenset(
    {"никто", "никогда", "нельзя", "не", "ничего", "никакого", "хватит", "забудьте"}
)
# Secret / insider framing.
_HOOK_SECRET = frozenset({"секрет", "правда", "честно", "признаюсь", "тайна", "мало"})
# Contradiction / expectation violation.
_HOOK_CONTRADICTION = frozenset({"неправ", "ошибался", "оказалось", "наоборот", "вранье", "врут"})
# Stakes / high-cost framing.
_HOOK_STAKES = frozenset({"потерял", "чуть", "провалил", "разорился", "уволили", "катастрофа"})
# Dead RU openers — admin / filler / soft warm-up that kills a hook.
_DEAD_OPENERS: tuple[tuple[str, ...], ...] = (
    ("так", "давайте"),
    ("ну", "в", "общем"),
    ("сегодня", "поговорим"),
    ("итак", "продолжим"),
    ("давайте", "сверим"),
)

_NUMBER_RE = re.compile(r"\d")
_PHRASE_BOUNDARY_RE = re.compile(r"[.!?…]")


@dataclass(frozen=True)
class ViralSignal:
    """The three sub-signals plus the fused bonus, all surfaced for debugging."""

    hook_strength: float  # [0, 1]
    quotable: float  # [0, 1]
    energy_density: float  # [0, 1]
    bonus: float  # [0, MAX_VIRAL_BONUS]


def _tokens(text: str) -> list[str]:
    """Whitespace split → normalized, non-empty tokens (reuses the punctuation norm)."""
    return [t for t in (_norm(w) for w in text.split()) if t]


def _starts_with_marker(tokens: list[str], markers: tuple[tuple[str, ...], ...]) -> bool:
    """True if any multi-word marker matches the very start of ``tokens``."""
    return any(tuple(tokens[: len(m)]) == m for m in markers)


def hook_strength(text: str) -> float:
    """Lexical viral-hook strength of the clip's opening, in [0, 1].

    Scans the first ``HOOK_WORD_COUNT`` words for hook families (number, negation,
    secret, contradiction, stakes, a question mark) — each present family adds a
    fixed step — then subtracts a penalty when the opening is a dead RU filler. The
    result is clamped to [0, 1]; a clip with no hook signal scores 0.
    """
    tokens = _tokens(text)
    if not tokens:
        return 0.0
    head = tokens[:HOOK_WORD_COUNT]
    head_set = set(head)
    raw_head = " ".join(text.split()[:HOOK_WORD_COUNT])

    score = 0.0
    if _NUMBER_RE.search(raw_head):
        score += 0.25  # a number/stat in the opening
    if head_set & _HOOK_NEGATION:
        score += 0.25
    if head_set & _HOOK_SECRET:
        score += 0.2
    if head_set & _HOOK_CONTRADICTION:
        score += 0.2
    if head_set & _HOOK_STAKES:
        score += 0.2
    if "?" in raw_head:
        score += 0.15  # a direct question opens a curiosity gap

    if _starts_with_marker(head, _DEAD_OPENERS):
        score -= 0.4  # a dead admin/filler opener kills the hook

    return round(max(0.0, min(1.0, score)), 6)


def quotable(text: str) -> float:
    """Presence of a short, punchy, self-contained declarative line, in [0, 1].

    Splits the clip into phrases on sentence punctuation and rewards the SHORTEST
    in-band phrase (``QUOTABLE_MIN_WORDS``..``QUOTABLE_MAX_WORDS`` words): a tight
    quote-card line. A clip that is one long run-on or only tiny fragments scores 0.
    The signal is binary-ish (a clip either has a quotable line or it does not).
    """
    phrases = [p.strip() for p in _PHRASE_BOUNDARY_RE.split(text) if p.strip()]
    for phrase in phrases:
        n = len(phrase.split())
        if QUOTABLE_MIN_WORDS <= n <= QUOTABLE_MAX_WORDS:
            return 1.0
    return 0.0


def energy_density(start: float, end: float, signals: object) -> float:
    """Emotional-peak density inside [start, end] from the DSP signals, in [0, 1].

    Counts loud energy bursts (``energy_peaks_s``) plus laughter-flagged windows
    (``audio_flags`` with ``laughter_conf`` above a small floor) that fall inside
    the span, then saturates at ``ENERGY_SATURATION_EVENTS``. Defensive at the
    seam: a None/partial signals bundle (a text-only run) reads as 0.0 — no DSP, no
    bonus — rather than raising.
    """
    if end <= start:
        return 0.0
    peaks = getattr(signals, "energy_peaks_s", ())
    flags = getattr(signals, "audio_flags", ())
    events = sum(1 for p in peaks if start <= p <= end)
    events += sum(
        1 for f in flags if start <= f.t <= end and f.laughter_conf >= LAUGHTER_FLAG_FLOOR
    )
    return round(min(1.0, events / ENERGY_SATURATION_EVENTS), 6)


def viral_signal(text: str, start: float, end: float, signals: object) -> ViralSignal:
    """Fuse the three sub-signals into one bounded additive bonus.

    The bonus is a weighted sum of the (already [0,1]) sub-signals scaled by
    ``MAX_VIRAL_BONUS``; the weights sum to 1.0 so a maxed-out clip earns exactly
    the cap. Pure and deterministic — identical inputs yield identical output.
    """
    h = hook_strength(text)
    q = quotable(text)
    e = energy_density(start, end, signals)
    fused = _W_HOOK * h + _W_QUOTABLE * q + _W_ENERGY * e
    return ViralSignal(
        hook_strength=h,
        quotable=q,
        energy_density=e,
        bonus=round(fused * MAX_VIRAL_BONUS, 4),
    )
