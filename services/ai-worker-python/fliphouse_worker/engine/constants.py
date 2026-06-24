"""Leaf engine constants — imported by both heavy modules and leaf consumers.

This module imports NOTHING from the rest of the package, so it can be pulled in
from anywhere without risking a circular import. ``SAFETY_CAP`` lives here (not in
``cascade.py``) precisely so ``clipping/asd_config.py`` can read it WITHOUT importing
``engine.cascade`` — which would form a cycle (cascade → escalation → clipping →
render → speaker_region → asd_config → cascade) that breaks a cold
``import fliphouse_worker.engine.cascade``. ``cascade.py`` re-exports ``SAFETY_CAP``
for back-compat, so existing ``from .cascade import SAFETY_CAP`` callers are unchanged.
"""

from __future__ import annotations

# Hard ceiling on emitted clips (anti-pathological), NOT the selection gate. The
# selection gate is ``DEFAULT_QUALITY_THRESHOLD``; this only bounds the worst case.
SAFETY_CAP = 40
