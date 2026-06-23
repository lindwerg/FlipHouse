"""Wire a text→score callable through the eval-harness (P2-S3).

Keeps the eval seam decoupled from the adapter: unit tests inject a deterministic
mock scorer; the guarded live test injects a real ClipScorer-backed callable.

RATIFIED FLOORS (P2 eval gate — these are the locked acceptance bar, not drafts):

* ``RATIFIED_MIN_SPEARMAN = 0.7`` — the model's clip ranking must agree strongly
  with human judgment. 0.7 is the conventional "strong monotonic agreement"
  threshold (Cohen); below it the ordering is too noisy to trust which clip wins.
* ``RATIFIED_MIN_DISPERSION = 15.0`` — aggregate scores (0-100) must spread, not
  cluster. 15 std means a typical clip sits ≳15 points off the mean, so the top
  pick is meaningfully separated from the field instead of every clip scoring
  "~78". The structural seed std is ~31.5, so 15 is a comfortable floor a real
  scorer clears while still failing a flat/clustered one.
* ``RATIFIED_MIN_DIVERGENCE = 0.20`` — the rubric's sub-scores must assess
  *distinct* dimensions, not collapse to one signal. Measured as
  ``1 - mean(|pairwise pearson|)`` over the sub-score dimensions across clips
  (0 = perfect lockstep, 1 = independent). 0.20 rejects a model that returns the
  same number for every dimension (divergence 0) while accepting the strongly-but
  -imperfectly correlated dimensions a coherent rubric naturally produces (hook
  and payoff covary, but emotion/pacing/visual/audio carry their own signal).

These floors were chosen against the bootstrap SEED set (``dataset.py``). The seed
is a deliberately-unambiguous BENCHMARK, not human ground truth; final ratification
against a HUMAN-LABELED set (15-20 clips the founder scores in the dashboard) is
the P2-S7 checkpoint — load that set via ``load_clips`` and re-confirm these floors
hold before promotion. The numbers themselves do not move; the evidence behind them
graduates from "seed-calibrated" to "human-confirmed".
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence

from ..eval import SEED_CLIPS, EvalReport, LabeledClip, evaluate

RATIFIED_MIN_SPEARMAN = 0.7
RATIFIED_MIN_DISPERSION = 15.0
RATIFIED_MIN_DIVERGENCE = 0.20

# Back-compat aliases (the names callers/tests already import).
DEFAULT_MIN_SPEARMAN = RATIFIED_MIN_SPEARMAN
DEFAULT_MIN_DISPERSION = RATIFIED_MIN_DISPERSION
DEFAULT_MIN_DIVERGENCE = RATIFIED_MIN_DIVERGENCE


def run_eval(
    scorer_fn: Callable[[str], float],
    clips: Sequence[LabeledClip] = SEED_CLIPS,
    *,
    min_spearman: float = RATIFIED_MIN_SPEARMAN,
    min_dispersion: float = RATIFIED_MIN_DISPERSION,
    min_divergence: float = RATIFIED_MIN_DIVERGENCE,
    sub_scores_fn: Callable[[str], Mapping[str, float]] | None = None,
) -> EvalReport:
    """Run the gate. ``scorer_fn`` yields each clip's aggregate; the optional
    ``sub_scores_fn`` yields its per-dimension sub-scores so the divergence gate
    activates. With no ``sub_scores_fn`` the divergence gate is inert (text-only
    callers that keep only the aggregate keep passing unchanged).
    """
    predicted = {clip.clip_id: scorer_fn(clip.text) for clip in clips}
    sub_scores = (
        {clip.clip_id: sub_scores_fn(clip.text) for clip in clips}
        if sub_scores_fn is not None
        else None
    )
    return evaluate(
        predicted,
        clips,
        min_spearman=min_spearman,
        min_dispersion=min_dispersion,
        sub_scores=sub_scores,
        min_divergence=min_divergence,
    )
