"""Unit coverage for engine/normalize.py internals — env knob + edge cases (RANK-1)."""

from __future__ import annotations

from dataclasses import dataclass

from fliphouse_worker.engine.normalize import normalized_rank_values


@dataclass(frozen=True)
class _Scored:
    aggregate: float
    model_used: str


@dataclass(frozen=True)
class _Clip:
    scored: _Scored


def _clip(a: float, m: str) -> _Clip:
    return _Clip(_Scored(a, m))


def test_empty_input_returns_empty():
    assert normalized_rank_values([]) == []


def test_env_offsets_parsed_and_applied(monkeypatch):
    # A valid JSON baseline in the env is read by the default (no explicit offsets) path.
    monkeypatch.setenv("CLIP_MODEL_OFFSETS", '{"flash": 50.0}')
    clips = [_clip(70.0, "flash"), *[_clip(80.0, "big") for _ in range(3)]]
    rv = normalized_rank_values(clips)  # no explicit offsets → reads env
    # flash baseline 50 → (70-50)/spread is positive and large vs big group z≈0.
    assert rv[0] > 0.0


def test_env_offsets_bad_json_ignored(monkeypatch):
    monkeypatch.setenv("CLIP_MODEL_OFFSETS", "{not json")
    clips = [_clip(70.0, "flash"), *[_clip(80.0, "big") for _ in range(3)]]
    # falls back to the reference mean — no crash, deterministic.
    rv = normalized_rank_values(clips)
    assert len(rv) == 4


def test_env_offsets_non_dict_ignored(monkeypatch):
    monkeypatch.setenv("CLIP_MODEL_OFFSETS", "[1, 2, 3]")
    clips = [_clip(70.0, "flash"), *[_clip(80.0, "big") for _ in range(3)]]
    assert len(normalized_rank_values(clips)) == 4


def test_env_offsets_non_number_values_filtered(monkeypatch):
    # a bool / string value is dropped (bool is NOT a number here), the float kept.
    monkeypatch.setenv("CLIP_MODEL_OFFSETS", '{"flash": 50.0, "bad": true, "s": "x"}')
    clips = [_clip(70.0, "flash"), *[_clip(80.0, "big") for _ in range(3)]]
    rv = normalized_rank_values(clips)
    assert rv[0] > 0.0  # the valid flash baseline still applied


def test_env_offsets_empty_unset(monkeypatch):
    monkeypatch.delenv("CLIP_MODEL_OFFSETS", raising=False)
    clips = [_clip(70.0, "flash"), *[_clip(80.0, "big") for _ in range(3)]]
    assert len(normalized_rank_values(clips)) == 4
