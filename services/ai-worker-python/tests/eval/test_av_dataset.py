"""Unit coverage for eval/av_dataset.py — manifest parsing + relative-path resolution."""

import json

import pytest

from fliphouse_worker.eval import AvLabeledClip, load_av_clips

_ENTRY = {
    "clip_id": "c1",
    "text": "и тут он сказал то, после чего повисла тишина",
    "human_score": 82,
    "clip_path": "clips/c1.webm",
    "duration_s": 31.5,
}


def _write(tmp_path, data):
    p = tmp_path / "manifest.json"
    p.write_text(json.dumps(data), encoding="utf-8")
    return p


def test_load_av_clips_parses_manifest(tmp_path):
    clips = load_av_clips(_write(tmp_path, [_ENTRY]))
    assert len(clips) == 1
    c = clips[0]
    assert isinstance(c, AvLabeledClip)
    assert (c.clip_id, c.text, c.human_score, c.duration_s) == (
        "c1",
        _ENTRY["text"],
        82,
        31.5,
    )


def test_load_av_clips_resolves_relative_clip_path(tmp_path):
    clips = load_av_clips(_write(tmp_path, [_ENTRY]))
    assert clips[0].clip_path == (tmp_path / "clips/c1.webm").resolve()


def test_load_av_clips_rejects_non_list(tmp_path):
    with pytest.raises(ValueError):
        load_av_clips(_write(tmp_path, {"clip_id": "c1"}))


def test_load_av_clips_missing_key_raises(tmp_path):
    broken = {k: v for k, v in _ENTRY.items() if k != "duration_s"}
    with pytest.raises(KeyError):
        load_av_clips(_write(tmp_path, [broken]))
