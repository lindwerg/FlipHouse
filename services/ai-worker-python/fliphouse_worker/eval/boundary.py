"""Boundary-quality metric for the sentence-end heuristic (TRANS-3).

The live boundary path snaps a clip's END to a restored sentence-end. With native
GigaAM-v3 punctuation projected onto the word stream (TRANS-1) that signal is the
model's own ``.``/``!``/``?``; the pause-only heuristic in ``engine/punctuation.py``
(``SENT_PAUSE_S``/``LONG_PAUSE_S``) is the license-clean FALLBACK for words a
provider left un-punctuated.

This module measures how good that heuristic is, so the pause thresholds are
JUSTIFIED by a number instead of asserted. ``boundary_scores`` runs
``annotate_sentence_ends`` over a word list whose TRUE sentence-end indices are
hand-marked and returns precision / recall / F-beta of the predicted ``sent_end``
flags against the truth.

PRECISION is favored (``beta < 1`` in :func:`f_beta`): a FALSE sentence-end drags a
clip's tail onto a mid-thought cut (the founder complaint), whereas a MISSED one
merely leaves the tail where a later signal can still finish it. The
``BOUNDARY_MIN_PRECISION`` gate below encodes that bias; it is wired into the test
suite as a regression floor so a future threshold change that starts inventing
false sentence-ends fails CI.

No scipy/numpy — small, exact, pure-python (matches ``eval/metrics.py``).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from ..engine.punctuation import PunctFn, annotate_sentence_ends

# Precision-favoring weight for the boundary F-score: beta<1 weights precision over
# recall. 0.5 → precision counts ~4× recall (beta**2 = 0.25), matching "a false
# sentence-end is far worse than a missed one" (punctuation.py:14-15).
BOUNDARY_F_BETA = 0.5

# Regression floor for the pause-only fallback heuristic on the hand-marked RU
# fixture (tests/eval/test_boundary.py). This is the OPERATING POINT the current
# SENT_PAUSE_S/LONG_PAUSE_S land on; it is a GATE, not a calibration claim — a live,
# founder-supplied labeled set would refine the exact thresholds, but this floor
# guarantees a future tuning change can never regress precision below it unnoticed.
BOUNDARY_MIN_PRECISION = 1.0


@dataclass(frozen=True)
class BoundaryReport:
    """Precision/recall/F-beta of predicted sentence-ends vs. hand-marked truth."""

    n_words: int
    n_true: int
    n_predicted: int
    true_positives: int
    precision: float
    recall: float
    f_beta: float


def f_beta(precision: float, recall: float, *, beta: float = BOUNDARY_F_BETA) -> float:
    """F-beta of precision/recall; ``beta<1`` favors precision. 0.0 when both are 0."""
    b2 = beta * beta
    denom = b2 * precision + recall
    if denom == 0:
        return 0.0
    return (1 + b2) * precision * recall / denom


def boundary_scores(
    words: Sequence[dict],
    true_end_indices: Sequence[int],
    *,
    punct_fn: PunctFn | None = None,
) -> BoundaryReport:
    """Run the sentence-end annotator and score its flags against hand-marked truth.

    ``words`` is the flat ``[{word, start, end}]`` list; ``true_end_indices`` are the
    indices whose word ENDS a real sentence. ``punct_fn`` is forwarded verbatim so a
    caller can score the model-injected path too (default ``None`` = the pause-only
    fallback, the load-bearing live heuristic this gate guards).
    """
    annotated = annotate_sentence_ends(words, punct_fn=punct_fn)
    predicted = {i for i, w in enumerate(annotated) if w["sent_end"]}
    truth = set(true_end_indices)

    tp = len(predicted & truth)
    precision = tp / len(predicted) if predicted else (1.0 if not truth else 0.0)
    recall = tp / len(truth) if truth else 1.0
    return BoundaryReport(
        n_words=len(words),
        n_true=len(truth),
        n_predicted=len(predicted),
        true_positives=tp,
        precision=precision,
        recall=recall,
        f_beta=f_beta(precision, recall),
    )
