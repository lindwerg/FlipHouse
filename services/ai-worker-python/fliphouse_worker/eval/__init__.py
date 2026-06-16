"""Virality eval-harness (P2-S1) — makes "maximal virality" measurable."""

from .dataset import SEED_CLIPS, LabeledClip, load_clips
from .metrics import (
    EvalReport,
    evaluate,
    score_dispersion,
    spearman_rank_correlation,
)

__all__ = [
    "SEED_CLIPS",
    "EvalReport",
    "LabeledClip",
    "evaluate",
    "load_clips",
    "score_dispersion",
    "spearman_rank_correlation",
]
