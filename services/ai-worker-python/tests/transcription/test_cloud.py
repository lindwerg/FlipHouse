"""CloudTranscriptionProvider — GigaAM-v3 stub behind an injected fake transport."""

from __future__ import annotations

from fliphouse_worker.transcription import CloudTranscriptionProvider

# Canned GigaAM-v3-shaped Russian payload (clean Cyrillic tokens, no leading space).
GIGAAM_PAYLOAD = {
    "duration": 2.0,
    "segments": [
        {
            "start": 0.0,
            "end": 2.0,
            "words": [
                {"word": "Я", "start": 0.0, "end": 0.4},
                {"word": "потерял", "start": 0.4, "end": 1.2},
                {"word": "миллион", "start": 1.2, "end": 2.0},
            ],
        },
    ],
}


def test_cloud_transcribe_offline_with_fake_transport():
    seen = {}

    def transport(audio_ref, language):
        seen["ref"] = audio_ref
        seen["lang"] = language
        return GIGAAM_PAYLOAD

    provider = CloudTranscriptionProvider(transport=transport)
    t = provider.transcribe("r2://job/audio.wav")

    assert seen == {"ref": "r2://job/audio.wav", "lang": "ru"}
    assert t.engine == "gigaam-v3"
    assert t.duration == 2.0
    # clean GigaAM tokens gained the leading space via normalize.
    assert [w.word for w in t.word_segments[0].words] == [" Я", " потерял", " миллион"]
    assert t.segments[0].text == "Я потерял миллион"


def test_cloud_language_override_passed_to_transport():
    captured = {}

    def transport(audio_ref, language):
        captured["lang"] = language
        return {"segments": [], "duration": 0.0}

    CloudTranscriptionProvider(transport=transport, language="ru").transcribe("a", language="en")
    assert captured["lang"] == "en"


def test_cloud_tolerates_payload_without_duration():
    provider = CloudTranscriptionProvider(
        transport=lambda ref, lang: {
            "segments": [
                {"start": 0.0, "end": 1.0, "words": [{"word": "x", "start": 0.0, "end": 1.0}]}
            ]
        },
    )
    t = provider.transcribe("a")
    assert t.duration == 1.0  # inferred from the latest word end
