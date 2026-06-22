"""The stage registry the CLI dispatches over — the 6 Python-backed stages.

Mirrors ``apps/worker-node/src/stages/registry.ts`` PYTHON_STAGES: every stage
the Node worker spawns Python for resolves here, so a wired stage never hits the
fatal ``UNKNOWN_STAGE`` path. ``publish`` is a Node finalizer (it reads the
reframe manifest directly), not a subprocess — so there is no ``store`` stage.
"""

from __future__ import annotations

from collections.abc import Callable

from ._types import StageDeps
from .asr import asr_handler
from .asr_finalize import asr_finalize_handler
from .passthrough import passthrough_handler
from .reframe import reframe_handler
from .score import score_handler
from .transcode import transcode_handler

StageHandler = Callable[[dict], dict]


def build_handlers(deps: StageDeps | None = None) -> dict[str, StageHandler]:
    """Return ``{stage: handler}``. With no deps, build the real env-backed R2 client."""
    if deps is None:
        from .r2 import R2Client

        deps = StageDeps(r2=R2Client.from_env())
    d = deps
    return {
        "transcode": lambda req: transcode_handler(req, d),
        "asr": lambda req: asr_handler(req, d),
        # GigaAM-v3 GPU lane finalizer: validate the parked raw payload → R2 contracts.
        "asr-finalize": lambda req: asr_finalize_handler(req, d),
        "score": lambda req: score_handler(req, d),
        "reframe": lambda req: reframe_handler(req, d),
        "caption": lambda req: passthrough_handler(req, d),
        "banner": lambda req: passthrough_handler(req, d),
    }
