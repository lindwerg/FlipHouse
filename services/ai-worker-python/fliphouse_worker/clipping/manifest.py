"""manifest.json schema for the vertical-render output (P2-2.4 render).

The manifest is the render leg's public contract: the dashboard reads it to show
the ranked 9:16 clips. ``sub_scores`` and ``modalities_used`` are forwarded
OPAQUELY from the scorer's ``ScoredClip`` — this module never re-keys them, so it
stays in lock-step with ``scoring.aggregate.SCORE_DIMS`` (hook/emotion/payoff/
visual/audio/pacing) and the real modalities (text/video/audio) without drift.
``to_dict`` emits a fixed key order so a byte-shape golden can pin it.
"""

from __future__ import annotations

from dataclasses import dataclass

MANIFEST_SCHEMA_VERSION: int = 2  # v2: dynamic-reframe segment_count (P2 reframe steps 3+4)
ENGINE_NAME: str = "fliphouse-cpu-mediapipe-v1"


@dataclass(frozen=True)
class ClipEntry:
    """One ranked clip's metadata in the manifest (0 = best)."""

    rank: int
    score: float
    sub_scores: dict[str, int]
    confidence: int
    start_time: float
    end_time: float
    duration_s: float
    width: int
    height: int
    path: str
    title: str
    used_video: bool
    model_used: str
    modalities_used: list[str]
    segment_count: int = 1  # fill-crop render segments concatenated (1 = fast path)
    caption_band: dict | None = None  # source burned-in caption band, or None (fail-open)

    def to_dict(self) -> dict[str, object]:
        """JSON-safe dict with a fixed key order (pinned by the byte-shape golden)."""
        return {
            "rank": self.rank,
            "score": self.score,
            "sub_scores": dict(self.sub_scores),
            "confidence": self.confidence,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration_s": self.duration_s,
            "width": self.width,
            "height": self.height,
            "path": self.path,
            "title": self.title,
            "used_video": self.used_video,
            "model_used": self.model_used,
            "modalities_used": list(self.modalities_used),
            "segment_count": self.segment_count,
            "caption_band": dict(self.caption_band) if self.caption_band is not None else None,
        }


@dataclass(frozen=True)
class RenderManifest:
    """The full render output descriptor written to ``manifest.json``."""

    schema_version: int
    source: str
    engine: str
    generated_at: str
    resolution: list[int]
    clip_count: int
    clips: tuple[ClipEntry, ...]
    # Cost-of-goods-sold for this job in integer micro-USD (1e6 scale, NO float) —
    # what the pipeline spent (GPU + LLM) to produce these clips. The Node ``publish``
    # finalizer forwards it to the COGS sink so revenue-minus-COGS margin reporting is
    # possible (BILL-3). Defaults to 0: the per-stage GPU-seconds + OpenRouter token
    # cost accumulation that populates a real figure is a documented follow-up (it
    # spans the asr/score stages, not just render). The PLUMBING ships now so a real
    # value lands as data the moment those stages report it.
    cost_usd_micros: int = 0

    def to_dict(self) -> dict[str, object]:
        """JSON-safe dict with a fixed key order; clips projected via ``ClipEntry.to_dict``."""
        return {
            "schema_version": self.schema_version,
            "source": self.source,
            "engine": self.engine,
            "generated_at": self.generated_at,
            "resolution": list(self.resolution),
            "clip_count": self.clip_count,
            "clips": [entry.to_dict() for entry in self.clips],
            "cost_usd_micros": self.cost_usd_micros,
        }
