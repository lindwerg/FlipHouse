"""One-Euro adaptive low-pass filter (P2-2.4 render) — Casiez, Roussel & Vogel.

Smooths the speaker-crop center over time so the 9:16 window tracks without
jitter at rest yet still follows a fast move. Adaptive: the cutoff rises with
signal speed, so a still subject is held rock-steady while a quick pan is not
lagged. ``reset`` snaps state to a hard scene cut (no smoothing across a shot
boundary). Mutable by design — it carries per-stream filter state.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

ONE_EURO_MIN_CUTOFF: float = 0.8
ONE_EURO_BETA: float = 0.15
ONE_EURO_D_CUTOFF: float = 1.0
EPS: float = 1e-6


def _alpha(t_e: float, cutoff: float) -> float:
    """Smoothing factor for a sampling interval ``t_e`` at the given ``cutoff`` Hz."""
    r = 2.0 * math.pi * cutoff * t_e
    return r / (r + 1.0)


@dataclass
class OneEuroFilter:
    """1-D adaptive low-pass. Mutable by design — carries filter state across samples."""

    min_cutoff: float = ONE_EURO_MIN_CUTOFF
    beta: float = ONE_EURO_BETA
    d_cutoff: float = ONE_EURO_D_CUTOFF
    _x_prev: float | None = None
    _dx_prev: float = 0.0
    _t_prev: float | None = None

    def reset(self, x: float, t: float) -> None:
        """Snap state to ``(x, t)`` — used at a scene-cut hard boundary. Clears velocity."""
        self._x_prev, self._dx_prev, self._t_prev = x, 0.0, t

    def filter(self, x: float, t: float) -> float:
        """Return the smoothed value for raw sample ``x`` at timestamp ``t`` seconds."""
        if self._t_prev is None:
            self._x_prev, self._t_prev = x, t
            return x
        t_e = max(t - self._t_prev, EPS)  # EPS guard: a duplicate timestamp can't divide by 0
        dx = (x - self._x_prev) / t_e
        edx = self._dx_prev + _alpha(t_e, self.d_cutoff) * (dx - self._dx_prev)
        cutoff = self.min_cutoff + self.beta * abs(edx)
        x_hat = self._x_prev + _alpha(t_e, cutoff) * (x - self._x_prev)
        self._x_prev, self._dx_prev, self._t_prev = x_hat, edx, t
        return x_hat
