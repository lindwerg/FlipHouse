"""Boundary-quality gate for the sentence-end heuristic (TRANS-3).

A hand-marked RU fixture: each tuple is ``(word, start, end)`` and the TRUE
sentence-end word indices are listed separately. The gate asserts the pause-only
FALLBACK heuristic hits ``BOUNDARY_MIN_PRECISION`` (precision-favored: a false
sentence-end is the founder's mid-thought-cut complaint), and that NATIVE GigaAM
punctuation — when projected onto the words — is recovered at full recall.

These are real RU sentences with realistic timing; this is regression test data,
not a fabricated calibration claim. A live founder-labeled set would refine the
exact thresholds, but this floor guarantees no tuning change regresses precision.
"""

from __future__ import annotations

from fliphouse_worker.eval.boundary import (
    BOUNDARY_F_BETA,
    BOUNDARY_MIN_PRECISION,
    boundary_scores,
    f_beta,
)

# Two RU sentences. Sentence 1 ends at "деньги" (idx 4) with a LONG 0.8s pause after;
# sentence 2 ends at "сразу" (idx 9), the last word. Inner gaps are tiny (no false
# stop). The next word after the long pause ("Поэтому") is capitalized — a corroborating
# fresh-start cue. This is the pause-only path: NO terminal punctuation on any token.
_PAUSE_ROWS = [
    ("сегодня", 0.0, 0.4),
    ("я", 0.45, 0.55),
    ("расскажу", 0.6, 1.1),
    ("про", 1.15, 1.4),
    ("деньги", 1.45, 2.0),  # idx 4 — sentence-1 terminus (long pause follows)
    ("Поэтому", 2.8, 3.3),  # +0.8s gap → LONG_PAUSE_S; capitalized fresh start
    ("слушай", 3.35, 3.7),
    ("внимательно", 3.75, 4.4),
    ("прямо", 4.45, 4.8),
    ("сразу", 4.85, 5.3),  # idx 9 — sentence-2 terminus (last word)
]
_PAUSE_TRUE_ENDS = [4, 9]

# The SAME two sentences but with native GigaAM punctuation projected onto the
# terminus words (as transcription/normalize.py does). Recall must be perfect AND
# precision must stay 1.0 — punctuation is the authoritative signal.
_PUNCT_ROWS = [
    ("сегодня", 0.0, 0.4),
    ("я", 0.45, 0.55),
    ("расскажу", 0.6, 1.1),
    ("про", 1.15, 1.4),
    ("деньги.", 1.45, 2.0),  # native terminal '.'
    ("поэтому", 2.1, 2.6),  # NO long pause here — only punctuation should fire
    ("слушай", 2.65, 3.0),
    ("внимательно", 3.05, 3.7),
    ("прямо", 3.75, 4.1),
    ("сразу.", 4.15, 4.6),  # native terminal '.'
]
_PUNCT_TRUE_ENDS = [4, 9]


def _words(rows):
    return [{"word": w, "start": s, "end": e} for w, s, e in rows]


def test_f_beta_favors_precision():
    # beta=0.5 → with equal-ish inputs, weighting tilts toward precision.
    high_p = f_beta(1.0, 0.5, beta=BOUNDARY_F_BETA)
    high_r = f_beta(0.5, 1.0, beta=BOUNDARY_F_BETA)
    assert high_p > high_r


def test_f_beta_zero_when_both_zero():
    assert f_beta(0.0, 0.0) == 0.0


def test_pause_fallback_meets_precision_floor():
    report = boundary_scores(_words(_PAUSE_ROWS), _PAUSE_TRUE_ENDS)
    # The GATE: the pause-only heuristic must not invent false sentence-ends.
    assert report.precision >= BOUNDARY_MIN_PRECISION, (
        f"pause heuristic precision regressed below floor: {report.precision} "
        f"(predicted={report.n_predicted}, tp={report.true_positives})"
    )
    # It should also catch the strong long-pause boundary (recall > 0).
    assert report.recall > 0.0


def test_native_punctuation_is_recovered_at_full_recall():
    report = boundary_scores(_words(_PUNCT_ROWS), _PUNCT_TRUE_ENDS)
    # Native '.' on both termini → every true end found, none invented.
    assert report.recall == 1.0
    assert report.precision == 1.0
    assert report.f_beta == 1.0


def test_no_true_ends_no_predictions_is_perfect():
    # A short run with no sentence ends and no firing heuristic scores 1.0/1.0.
    rows = [("а", 0.0, 0.2), ("б", 0.25, 0.45), ("в", 0.5, 0.7)]
    report = boundary_scores(_words(rows), [])
    assert report.precision == 1.0
    assert report.recall == 1.0


def test_false_prediction_drops_precision_below_floor():
    # A 0.8s gap with a capitalized next word fires the heuristic; if that index is
    # NOT a true end, precision drops — proving the gate would CATCH a regression.
    rows = [
        ("слово", 0.0, 0.5),
        ("Другое", 1.4, 2.0),  # +0.9s gap, capitalized → predicted sent_end at idx 0
        ("ещё", 2.05, 2.4),
    ]
    report = boundary_scores(_words(rows), [2])  # truth: only the last word ends a sentence
    assert report.n_predicted >= 1
    assert report.precision < BOUNDARY_MIN_PRECISION
