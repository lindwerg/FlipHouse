"""Virality eval-harness (P2-S1) — makes "maximal virality" measurable."""

from .av_dataset import AvLabeledClip, load_av_clips
from .cutover import CutoverReport, evaluate_cutover
from .dataset import SEED_CLIPS, LabeledClip, load_clips
from .metrics import (
    EvalReport,
    evaluate,
    score_dispersion,
    spearman_rank_correlation,
    sub_score_divergence,
)

__all__ = [
    "SEED_CLIPS",
    "AvLabeledClip",
    "CutoverReport",
    "EvalReport",
    "LabeledClip",
    "evaluate",
    "evaluate_cutover",
    "load_av_clips",
    "load_clips",
    "score_dispersion",
    "spearman_rank_correlation",
    "sub_score_divergence",
]
