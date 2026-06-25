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
from dataclasses import dataclass

from ..eval import SEED_CLIPS, EvalReport, LabeledClip, evaluate
from .threshold_calibration import percentile_threshold

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


@dataclass(frozen=True)
class ThresholdEvalReport:
    """Does the calibrated threshold actually BIND on a real score distribution?

    RANK-4 / EVAL-1: the synthetic seed validates the rubric's RANKING but never the
    SELECTION threshold. On the live 2h run the absolute-55 cut was bypassed — only
    1/20 cleared it and the duration floor silently governed. This report asserts
    that on a given run's distribution the percentile cut keeps a count INSIDE the
    founder's target band [``min_keep``, ``max_keep``], i.e. the threshold (not a
    pure-duration constant) is doing the selecting.
    """

    n: int
    threshold: float
    kept: int
    min_keep: int
    max_keep: int
    floor: int
    floor_governs: bool
    passed: bool


def evaluate_threshold_binding(
    rank_values: Sequence[float],
    target_percentile: float,
    *,
    min_keep: int,
    max_keep: int,
    floor: int,
) -> ThresholdEvalReport:
    """Assert the percentile threshold BINDS (keeps a sane count) on ``rank_values``.

    ``rank_values`` is a run's per-clip NORMALIZED scores (RANK-1 output). The cut is
    the ``target_percentile``; ``kept`` clips clear it. The gate passes iff the kept
    count lands in [``min_keep``, ``max_keep``] — the founder's target band. The
    pathological live failure (keeping ~1 of 20, the duration constant fully governing
    with zero quality content) fails ``min_keep``; over-selection fails ``max_keep``.
    ``floor_governs`` (``kept < floor``) is reported as a SIGNAL — a slight overlap of
    the threshold and floor bands is fine, so it is not an automatic fail; the cascade
    logs a WARNING when it actually fires at runtime. Pure, no network: feeds a
    recorded/golden distribution in CI.
    """
    if not rank_values:
        raise ValueError("need a non-empty score distribution")
    cut = percentile_threshold(rank_values, target_percentile)
    kept = sum(1 for v in rank_values if v >= cut)
    floor_governs = kept < floor
    passed = min_keep <= kept <= max_keep
    return ThresholdEvalReport(
        n=len(rank_values),
        threshold=cut,
        kept=kept,
        min_keep=min_keep,
        max_keep=max_keep,
        floor=floor,
        floor_governs=floor_governs,
        passed=passed,
    )
