"""Wire-contract dataclasses — the EXACT shapes shared with worker-node and the
webhook-receiver (already built against them).

The receiving end (``webhook-receiver`` → ``asr-finalize``) validates
``payload`` as ``{duration, language, segments: [{start, end, words: [{word,
start, end}]}]}``. These frozen dataclasses are the in-memory mirror; the
``to_dict`` projections produce the canonical JSON bodies we sign and POST.
"""

from __future__ import annotations

from dataclasses import dataclass

# Pinned literals that travel on every successful callback. The receiver keys
# off ``engine`` and the language tag, so these are part of the contract.
ENGINE_GIGAAM_V3 = "gigaam-v3"
LANGUAGE_RU = "ru"

STATUS_ACCEPTED = "accepted"
STATUS_PROCESSING = "processing"
STATUS_SUCCEEDED = "succeeded"
STATUS_FAILED = "failed"


@dataclass(frozen=True)
class Word:
    """A single recognized token with absolute (whole-media) timestamps."""

    word: str
    start: float
    end: float

    def to_dict(self) -> dict:
        return {"word": self.word, "start": self.start, "end": self.end}


@dataclass(frozen=True)
class Segment:
    """An utterance segment carrying its words; times are absolute, not offsets.

    ``text`` is the model's PUNCTUATED, NORMALIZED segment transcription
    (``v3_e2e_rnnt`` emits punctuation/casing at the SEGMENT level, never on the
    bare per-word tokens — see GigaAM-v3 README). It is carried verbatim so the
    downstream worker can recover sentence boundaries: the per-word stream is
    un-punctuated, so without this the only sentence-end signal is a pause
    heuristic. It is OPTIONAL/additive (default ``""``) so the wire contract stays
    backward-compatible with the receiver's existing validator."""

    start: float
    end: float
    words: tuple[Word, ...]
    text: str = ""

    def to_dict(self) -> dict:
        return {
            "start": self.start,
            "end": self.end,
            "text": self.text,
            "words": [w.to_dict() for w in self.words],
        }


@dataclass(frozen=True)
class RawPayload:
    """The ``payload`` object of a successful callback — what ``transcribe_audio``
    returns and what the receiver's ``validate_gigaam_payload`` validates."""

    duration: float
    language: str
    segments: tuple[Segment, ...]

    def to_dict(self) -> dict:
        return {
            "duration": self.duration,
            "language": self.language,
            "segments": [s.to_dict() for s in self.segments],
        }


@dataclass(frozen=True)
class SubmitRequest:
    """The validated ``/transcribe`` body (worker-node → this service)."""

    request_id: str
    audio_url: str
    language: str
    webhook_url: str
    output_prefix: str
