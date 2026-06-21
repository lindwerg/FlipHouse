"""Cross-language contract guard: the live Python manifest byte-shape MUST equal
the checked-in shared golden the TypeScript ``renderManifestSchema`` round-trips
(``packages/shared/src/manifest/manifest-contract.golden.json``).

If a dev changes ``RenderManifest.to_dict()`` without regenerating the shared
golden — or bumps the TS schema without the Python side — this test (and its TS
twin) goes red, instead of the dashboard silently breaking.
"""

import json
from pathlib import Path

from fliphouse_worker.clipping.manifest import (
    ENGINE_NAME,
    MANIFEST_SCHEMA_VERSION,
    ClipEntry,
    RenderManifest,
)

_SHARED_GOLDEN = (
    Path(__file__).resolve().parents[4]
    / "packages"
    / "shared"
    / "src"
    / "manifest"
    / "manifest-contract.golden.json"
)


def _golden_manifest() -> RenderManifest:
    """The exact manifest the shared golden encodes (mirrors test_manifest.py)."""
    return RenderManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source="tinkov-plata.mp4",
        engine=ENGINE_NAME,
        generated_at="2026-06-17T00:00:00Z",
        resolution=[1080, 1920],
        clip_count=1,
        clips=(
            ClipEntry(
                rank=0,
                score=87.5,
                sub_scores={
                    "hook": 90,
                    "emotion": 82,
                    "payoff": 88,
                    "visual": 84,
                    "audio": 80,
                    "pacing": 86,
                },
                confidence=90,
                start_time=123.0,
                end_time=168.0,
                duration_s=45.0,
                width=1080,
                height=1920,
                path="clip_00.mp4",
                title="t",
                used_video=True,
                model_used="google/gemini-3.5-flash",
                modalities_used=["text", "video", "audio"],
            ),
        ),
    )


def test_shared_golden_matches_live_to_dict():
    live = _golden_manifest().to_dict()
    # Round-trip through json so int/float coercion matches what the TS side parses.
    live = json.loads(json.dumps(live))
    checked_in = json.loads(_SHARED_GOLDEN.read_text(encoding="utf-8"))
    assert live == checked_in


def test_shared_golden_pins_the_schema_version():
    checked_in = json.loads(_SHARED_GOLDEN.read_text(encoding="utf-8"))
    assert checked_in["schema_version"] == MANIFEST_SCHEMA_VERSION
