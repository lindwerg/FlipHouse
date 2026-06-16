"""Audio/visual labeled-clip manifest for the Lane-2 live A/V eval (P2-S6).

The deterministic seed eval (``dataset.py``) is TEXT-only and stays the sole CI
gate. Proving "native A/V beats text-only on Spearman" needs real video the
founder hand-cuts, so this loads a manifest of ``AvLabeledClip`` — each pointing
at a real WebM clip on disk — consumed ONLY by the guarded live test
(``FLIPHOUSE_LIVE_GEMINI`` + ``FLIPHOUSE_AV_MANIFEST``). It is never imported by
the deterministic path and never widens ``LabeledClip``.

Manifest = a JSON list of objects::

    {"clip_id": "c1", "text": "...transcript...", "human_score": 82,
     "clip_path": "clips/c1.webm", "duration_s": 31.5}

``clip_path`` is resolved relative to the manifest's own directory (parallels
``dataset.py::load_clips``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class AvLabeledClip:
    clip_id: str
    text: str
    human_score: int  # human virality judgment, 0-100
    clip_path: Path  # absolute path to the WebM clip, resolved against the manifest dir
    duration_s: float  # clip length — passed identically to text & A/V scoring runs


def load_av_clips(path: str | Path) -> list[AvLabeledClip]:
    """Load an A/V manifest (JSON list); resolve each ``clip_path`` against its dir."""
    manifest = Path(path)
    raw = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError("A/V manifest must be a JSON list of clip objects")
    base = manifest.parent
    return [
        AvLabeledClip(
            clip_id=item["clip_id"],
            text=item["text"],
            human_score=int(item["human_score"]),
            clip_path=(base / item["clip_path"]).resolve(),
            duration_s=float(item["duration_s"]),
        )
        for item in raw
    ]
