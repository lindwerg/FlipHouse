"""Contract-shape tests — the payload projection must match the receiver."""

from __future__ import annotations

from fliphouse_gigaam.contracts import RawPayload, Segment, SubmitRequest, Word


def test_word_to_dict_shape():
    assert Word("привет", 0.0, 1.0).to_dict() == {"word": "привет", "start": 0.0, "end": 1.0}


def test_segment_to_dict_nests_words_and_carries_text():
    seg = Segment(0.0, 2.0, (Word("a", 0.0, 1.0), Word("b", 1.0, 2.0)), text="A b.")
    assert seg.to_dict() == {
        "start": 0.0,
        "end": 2.0,
        "text": "A b.",
        "words": [
            {"word": "a", "start": 0.0, "end": 1.0},
            {"word": "b", "start": 1.0, "end": 2.0},
        ],
    }


def test_segment_text_defaults_empty_backward_compatible():
    # ``text`` is additive/optional — a Segment built without it serializes "" so
    # the receiver's existing validator (which ignores unknown/extra keys) is safe.
    seg = Segment(0.0, 2.0, (Word("a", 0.0, 1.0),))
    assert seg.to_dict()["text"] == ""


def test_raw_payload_to_dict_matches_receiver_contract():
    payload = RawPayload(
        duration=2.0,
        language="ru",
        segments=(Segment(0.0, 2.0, (Word("x", 0.0, 2.0),), text="Икс."),),
    )
    assert payload.to_dict() == {
        "duration": 2.0,
        "language": "ru",
        "segments": [
            {
                "start": 0.0,
                "end": 2.0,
                "text": "Икс.",
                "words": [{"word": "x", "start": 0.0, "end": 2.0}],
            },
        ],
    }


def test_submit_request_is_frozen():
    req = SubmitRequest("r1", "https://a/x", "ru", "https://b/cb", "intermediate/h/asr")
    assert req.request_id == "r1"
    assert req.output_prefix == "intermediate/h/asr"
