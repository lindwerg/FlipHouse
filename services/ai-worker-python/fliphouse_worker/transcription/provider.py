"""Transcription contract types + the provider seam (P2-S2.4).

The transcription stage emits TWO distinct, deliberately-separate contracts (the
adversarial review flagged conflating them as the bug that would bite the runner
step 2.5 and the P3 caption stage):

1. The **cascade transcript** dict ``{duration, language, engine, segments:
   [{start, end, text}]}`` — consumed via HARD SUBSCRIPT by ``engine/highlights.py``
   (``s["text"]``, ``segments[-1]["end"]``) and ``engine/recall.py``. Every segment
   therefore carries plain (non-optional) ``text``/``start``/``end`` keys.
2. The **word_segments.json** flat list ``[{start, end, words:[{word, start, end}]}]``
   (doc 01 §2) — consumed by caption burn-in (captacity, P3). Each ``word`` carries a
   LEADING SPACE (captacity convention).

:class:`Transcript` is the single in-memory value; ``to_cascade_dict`` and
``to_word_segments`` project it onto the two wire contracts. The
:class:`TranscriptionProvider` Protocol is the swap point — mirrors the engine's
``llm_fn`` / ``RecallFn`` injection style, so the CPU fallback and the (future,
GPU-lane) GigaAM-v3 primary are interchangeable without touching any consumer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable


@dataclass(frozen=True)
class Word:
    """A single word with its timing. ``word`` carries a LEADING SPACE (captacity)."""

    word: str
    start: float
    end: float


@dataclass(frozen=True)
class WordSegment:
    """An utterance span carrying its per-word timings (the doc 01 §2 unit)."""

    start: float
    end: float
    words: tuple[Word, ...]


@dataclass(frozen=True)
class Segment:
    """An utterance span carrying plain text (the cascade-consumed unit)."""

    start: float
    end: float
    text: str


@dataclass(frozen=True)
class Transcript:
    """The normalized transcription result; projects onto both wire contracts."""

    duration: float
    language: str
    engine: str
    segments: tuple[Segment, ...]
    word_segments: tuple[WordSegment, ...]

    def to_cascade_dict(self) -> dict:
        """Project onto the dict the scoring cascade consumes (hard-subscript safe)."""
        return {
            "duration": self.duration,
            "language": self.language,
            "engine": self.engine,
            "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in self.segments],
        }

    def to_word_segments(self) -> list[dict]:
        """Project onto the doc 01 §2 flat ``word_segments.json`` list (P3 captions)."""
        return [
            {
                "start": ws.start,
                "end": ws.end,
                "words": [{"word": w.word, "start": w.start, "end": w.end} for w in ws.words],
            }
            for ws in self.word_segments
        ]


@runtime_checkable
class TranscriptionProvider(Protocol):
    """The swap point: a provider turns an audio/video reference into a Transcript."""

    def transcribe(self, audio_ref: str, *, language: str | None = None) -> Transcript: ...
