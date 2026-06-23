"""Shared bounded thread-pool fan-out for the per-clip ffmpeg loops (ASK #6 Speed).

ffmpeg work is process-level parallelism, so a small ``ThreadPoolExecutor`` runs
several native encoders at once without the GIL ever mattering. ``ex.map``
preserves INPUT ORDER, so every caller assembles its results in the original
order → the output manifest stays byte-identical (same clips, same order); only
wall-clock changes.

Two seams, because the callers have OPPOSITE failure policies:

* ``ordered_threadpool_map`` — scoring's drop-and-continue: a per-item crash is
  CONTAINED to ``None`` (defence-in-depth, never lose the whole batch over one
  clip). This is the home of the pattern ``engine/scoring_fanout`` re-exports.
* ``strict_ordered_threadpool_map`` — render/caption's fail-CLOSED policy: a
  per-item exception PROPAGATES (a dropped paid clip is fatal, never silent).

Worker caps are small, named constants: a 30-clip job must not fork 30 native
encoders on a 2-vCPU box, so ``min(cap, len(items))`` bounds the fan-out.
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

logger = logging.getLogger(__name__)

# Bounded encoder fan-out: small enough that an N-clip job never thrashes a
# 2-vCPU / ~2 GB Railway task (each worker drives one native ffmpeg process).
MAX_RENDER_WORKERS = 4
MAX_CAPTION_WORKERS = 4

T = TypeVar("T")
R = TypeVar("R")
MapFn = Callable[[Callable[[T], R], Sequence[T]], "list[R]"]


def _isolated(fn: Callable[[T], R], item: T) -> R | None:
    """Run ``fn(item)``; an unanticipated crash is contained to ``None`` (defence-in-depth)."""
    try:
        return fn(item)
    except Exception:
        logger.warning("clip task crashed; dropping", exc_info=True)
        return None


def ordered_threadpool_map(
    fn: Callable[[T], R], items: Sequence[T], max_workers: int = MAX_RENDER_WORKERS
) -> list[R | None]:
    """Map ``fn`` over ``items`` concurrently, preserving order; a crash → ``None``.

    Empty input → ``[]`` (no executor constructed). Used where dropping one
    failed item and keeping the rest is the correct policy (scoring).
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as ex:
        return list(ex.map(lambda it: _isolated(fn, it), items))


def strict_ordered_threadpool_map(
    fn: Callable[[T], R], items: Sequence[T], max_workers: int = MAX_RENDER_WORKERS
) -> list[R]:
    """Map ``fn`` over ``items`` concurrently, preserving order; an exception PROPAGATES.

    Empty input → ``[]``. Used where a failed item is fatal and MUST NOT be
    silently dropped (render + caption fail-closed). ``ex.map`` re-raises the
    first worker exception when its result is consumed.
    """
    if not items:
        return []
    with ThreadPoolExecutor(max_workers=min(max_workers, len(items))) as ex:
        return list(ex.map(fn, items))
