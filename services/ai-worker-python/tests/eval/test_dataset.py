"""Tests for the eval-harness dataset (seed + loader, P2-S1)."""

import json

import pytest

from fliphouse_worker.eval.dataset import SEED_CLIPS, LabeledClip, load_clips


def test_seed_is_nonempty_and_spans_the_range():
    assert len(SEED_CLIPS) >= 8
    scores = [c.human_score for c in SEED_CLIPS]
    # A useful benchmark must span clearly-boring → clearly-viral.
    assert min(scores) <= 20
    assert max(scores) >= 85


def test_seed_clip_ids_are_unique():
    ids = [c.clip_id for c in SEED_CLIPS]
    assert len(ids) == len(set(ids))


def test_seed_scores_are_within_bounds():
    assert all(0 <= c.human_score <= 100 for c in SEED_CLIPS)
    assert all(c.text.strip() for c in SEED_CLIPS)


def test_load_clips_round_trips(tmp_path):
    path = tmp_path / "clips.json"
    payload = [
        {"clip_id": "x", "text": "hello", "human_score": 30},
        {"clip_id": "y", "text": "world", "human_score": 80},
    ]
    path.write_text(json.dumps(payload), encoding="utf-8")
    clips = load_clips(path)
    assert clips == [
        LabeledClip(clip_id="x", text="hello", human_score=30),
        LabeledClip(clip_id="y", text="world", human_score=80),
    ]


def test_load_clips_rejects_non_list(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text(json.dumps({"clip_id": "x"}), encoding="utf-8")
    with pytest.raises(ValueError, match="list of clip objects"):
        load_clips(path)
