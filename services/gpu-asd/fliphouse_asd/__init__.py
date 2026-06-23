"""FlipHouse LR-ASD GPU active-speaker service (REFRAME Phase 4).

A production-correct package: the ASGI app, the wire contracts, REAL HMAC
verification, and the validate→verify→score orchestration with the heavy LR-ASD
model call behind ONE injected seam. The GPU model (LR-ASD, Junhua-Liao/LR-ASD,
MIT, bundled weights — NO pyannote), the Docker image, and the Modal deploy live in
``modal_app.py`` (deploy-only, outside this package's 100%-coverage gate). The
injected seam whose real body needs a GPU is exercised by a live ``--selftest`` /
deploy, not by CI; everything around it (marshalling, HMAC, validation, shape
checks) is 100% unit-covered.
"""

from __future__ import annotations

from .app import AppDeps, create_app
from .contracts import ENGINE_LR_ASD, FaceRef, ScoreRequest, ScoreResponse
from .scoring import run_scoring
from .signing import (
    SIGNATURE_HEADER,
    TIMESTAMP_HEADER,
    compute_signature,
    verify_signature,
)
from .validate import parse_score_request

__all__ = [
    "AppDeps",
    "ENGINE_LR_ASD",
    "FaceRef",
    "SIGNATURE_HEADER",
    "ScoreRequest",
    "ScoreResponse",
    "TIMESTAMP_HEADER",
    "compute_signature",
    "create_app",
    "parse_score_request",
    "run_scoring",
    "verify_signature",
]
