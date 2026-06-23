"""Upstream LR-ASD ``evaluate_network`` adapter (DEPLOY-ONLY — GPU image only).

This is the ONE live-integration seam to validate on first deploy. It wraps the
stock LR-ASD per-track scorer (``Columbia_test.evaluate_network`` in
``Junhua-Liao/LR-ASD``): crop the 224x224 face video for a track, extract the synced
MFCC audio, run the network, and return a per-(sampled-)frame speaking score list.

It is intentionally kept OUT of the ``fliphouse_asd`` package (and thus out of the
100%-coverage gate) because it depends on torch/cv2 + the cloned LR-ASD repo on
PYTHONPATH, present only inside the Modal GPU image. Correctness is verified live via
``modal run modal_app.py`` against a real clip, not by unit tests.

Why a thin adapter rather than inlining upstream: the upstream crop/MFCC code is
verbatim-sensitive (the network expects exactly its preprocessing), so we call into
the repo's own functions instead of re-deriving them — keeping the accuracy the
published weights were trained for.
"""

from __future__ import annotations

# Resolved ONLY in the GPU image (the LR-ASD repo is cloned to /opt/LR-ASD and put on
# PYTHONPATH by modal_app.gpu_image). Importing this in CI fails — by design.
import cv2  # type: ignore[import-not-found]  # noqa: F401  (load-bearing in crop path)
import numpy  # type: ignore[import-not-found]

# Frames-per-second of the 224x224 face crop the network consumes (upstream default).
_CROP_FPS = 25


def evaluate_track(clip_path: str, track: dict, net) -> list[float]:
    """Return the per-sampled-frame speaking score for one face ``track``.

    DEPLOY-ONLY. Bridges our track dict (``{"frames": {sample_idx: box}}``) to the
    upstream scorer. On first deploy this is the function to wire to the exact
    ``evaluate_network`` signature in the pinned LR-ASD commit and validate against a
    known clip; until then it raises a clear, typed error rather than returning a
    plausible-but-wrong grid (the worker fails OPEN to its CPU heuristic on any
    non-2xx, so a loud failure here is the safe default).
    """
    raise NotImplementedError(
        "wire lr_asd_eval.evaluate_track to the upstream Columbia_test.evaluate_network "
        "on first GPU deploy; validate with `modal run modal_app.py` on a known clip"
    )


# Keep the numpy import load-bearing (the upstream crop/MFCC path uses it once wired).
_NUMPY = numpy
