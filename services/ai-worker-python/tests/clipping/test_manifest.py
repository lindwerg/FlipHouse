"""manifest — byte-shape golden against the REAL SCORE_DIMS, opaque sub-score forwarding."""

from fliphouse_worker.clipping.manifest import (
    ENGINE_NAME,
    MANIFEST_SCHEMA_VERSION,
    ClipEntry,
    RenderManifest,
)
from fliphouse_worker.scoring.aggregate import ALLOWED_MODALITIES, SCORE_DIMS


def _entry(rank: int) -> ClipEntry:
    return ClipEntry(
        rank=rank,
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
        path=f"clip_{rank:02d}.mp4",
        title="t",
        used_video=True,
        model_used="google/gemini-3.5-flash",
        modalities_used=["text", "video", "audio"],
    )


def test_clip_entry_sub_score_keys_are_the_real_score_dims():
    entry = _entry(0)
    assert set(entry.sub_scores) == set(SCORE_DIMS)
    assert set(entry.modalities_used) <= ALLOWED_MODALITIES


def test_manifest_to_dict_byte_shape():
    manifest = RenderManifest(
        schema_version=MANIFEST_SCHEMA_VERSION,
        source="tinkov-plata.mp4",
        engine=ENGINE_NAME,
        generated_at="2026-06-17T00:00:00Z",
        resolution=[1080, 1920],
        clip_count=1,
        clips=(_entry(0),),
    )
    assert manifest.to_dict() == {
        "schema_version": 1,
        "source": "tinkov-plata.mp4",
        "engine": "fliphouse-cpu-mediapipe-v1",
        "generated_at": "2026-06-17T00:00:00Z",
        "resolution": [1080, 1920],
        "clip_count": 1,
        "clips": [
            {
                "rank": 0,
                "score": 87.5,
                "sub_scores": {
                    "hook": 90,
                    "emotion": 82,
                    "payoff": 88,
                    "visual": 84,
                    "audio": 80,
                    "pacing": 86,
                },
                "confidence": 90,
                "start_time": 123.0,
                "end_time": 168.0,
                "duration_s": 45.0,
                "width": 1080,
                "height": 1920,
                "path": "clip_00.mp4",
                "title": "t",
                "used_video": True,
                "model_used": "google/gemini-3.5-flash",
                "modalities_used": ["text", "video", "audio"],
            }
        ],
    }


def test_clip_entry_forwards_sub_scores_opaquely():
    weird = {"hook": 1, "emotion": 2, "payoff": 3, "visual": 4, "audio": 5, "pacing": 6}
    entry = ClipEntry(
        rank=0,
        score=1.0,
        sub_scores=weird,
        confidence=50,
        start_time=0.0,
        end_time=1.0,
        duration_s=1.0,
        width=1080,
        height=1920,
        path="clip_00.mp4",
        title="t",
        used_video=False,
        model_used="m",
        modalities_used=["text"],
    )
    assert entry.to_dict()["sub_scores"] == weird
