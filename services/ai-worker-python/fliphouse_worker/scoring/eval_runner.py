"""Wire a text→score callable through the eval-harness (P2-S3).

Keeps the eval seam decoupled from the adapter: unit tests inject a deterministic
mock scorer; the guarded live test injects a real ClipScorer-backed callable.

Floors are conservative defaults, NOT founder-ratified. min_dispersion is set
below the seed's structural std (~31.5) because the first live run is a
CALIBRATION run — read the realized dispersion before locking the floor.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence

from ..eval import SEED_CLIPS, EvalReport, LabeledClip, evaluate

DEFAULT_MIN_SPEARMAN = 0.7
DEFAULT_MIN_DISPERSION = 15.0


def run_eval(
    scorer_fn: Callable[[str], float],
    clips: Sequence[LabeledClip] = SEED_CLIPS,
    *,
    min_spearman: float = DEFAULT_MIN_SPEARMAN,
    min_dispersion: float = DEFAULT_MIN_DISPERSION,
) -> EvalReport:
    predicted = {clip.clip_id: scorer_fn(clip.text) for clip in clips}
    return evaluate(predicted, clips, min_spearman=min_spearman, min_dispersion=min_dispersion)
