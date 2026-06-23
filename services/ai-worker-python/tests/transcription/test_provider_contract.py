"""Contract projection + Protocol-satisfaction + doc 01 §2 drift guard."""

from __future__ import annotations

from fliphouse_worker.transcription import (
    CloudTranscriptionProvider,
    TranscriptionProvider,
    normalize_segments,
)


def _sample():
    raw = [
        {
            "start": 0.0,
            "end": 1.0,
            "words": [
                {"word": "Привет", "start": 0.0, "end": 0.5},
                {"word": "мир", "start": 0.5, "end": 1.0},
            ],
        }
    ]
    return normalize_segments(raw, duration=1.0, language="ru", engine="gigaam-v3")


def test_cascade_dict_shape_is_hard_subscript_safe():
    # Mirrors what engine/highlights.py + recall.py consume via s["text"], s["start"]…
    d = _sample().to_cascade_dict()
    assert set(d) == {"duration", "language", "engine", "segments"}
    assert d["language"] == "ru"
    assert d["engine"] == "gigaam-v3"
    for seg in d["segments"]:
        assert set(seg) == {"start", "end", "text"}  # plain, non-optional keys
        assert isinstance(seg["text"], str)
        assert isinstance(seg["start"], float)
        assert isinstance(seg["end"], float)


def test_word_segments_matches_doc01_flat_list_contract():
    # doc 01 §2: word_segments.json = [{start,end,words:[{word,start,end}]}] — a FLAT
    # list, NOT a dict, with a LEADING SPACE in each word (captacity convention).
    ws = _sample().to_word_segments()
    assert isinstance(ws, list)
    for entry in ws:
        assert set(entry) == {"start", "end", "words"}
        for w in entry["words"]:
            assert set(w) == {"word", "start", "end"}
            assert w["word"].startswith(" ")  # leading-space invariant


def test_two_contracts_are_not_conflated():
    # The cascade dict must NOT carry word_segments, and the flat list must NOT
    # carry segment text — they are deliberately separate artifacts.
    t = _sample()
    assert "word_segments" not in t.to_cascade_dict()
    assert all("text" not in entry for entry in t.to_word_segments())


def test_cloud_provider_satisfies_the_protocol():
    cloud = CloudTranscriptionProvider(
        transport=lambda ref, lang: {"segments": [], "duration": 0.0}
    )
    assert isinstance(cloud, TranscriptionProvider)
