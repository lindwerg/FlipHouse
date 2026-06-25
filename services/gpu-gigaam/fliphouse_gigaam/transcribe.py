"""The ``transcribe_audio`` seam — local audio file → :class:`RawPayload`.

The DEFAULT implementation is the REAL GigaAM-v3 GPU call (``v3_e2e_rnnt`` model,
``transcribe_longform`` with pyannote VAD for the 2h case) and its body is
``# pragma: no cover`` — there is no GPU in CI. Unit tests inject a FAKE
``transcribe_audio`` returning a canned :class:`RawPayload`, so the orchestration
is fully covered without weights.

GigaAM ``transcribe_longform`` yields per-VAD-window results shaped roughly as a
list of ``{transcription, boundaries: (seg_start, seg_end), words: [{text, start,
end}]}`` where word times are RELATIVE to the window start. The mapping below
(``_map_longform_result``) is PURE and unit-tested: it renames ``text`` → ``word``,
offsets each word/segment time by the window's ``boundaries[0]``, and derives the
total ``duration`` from the latest segment end.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Protocol

from .contracts import LANGUAGE_RU, RawPayload, Segment, Word
from .errors import TranscriptionError


class _Longform(Protocol):
    """The subset of a GigaAM model we depend on (kept narrow for the fake)."""

    def transcribe_longform(self, audio_path: str) -> Sequence[dict]: ...


def _map_longform_result(windows: Sequence[dict], *, language: str) -> RawPayload:
    """PURE: GigaAM longform windows → contract :class:`RawPayload`.

    Each window's ``boundaries[0]`` is the absolute start; word/segment times in
    the window are relative and get that offset added. ``text`` is renamed to
    ``word``. ``duration`` is the maximum absolute segment end.
    """
    segments: list[Segment] = []
    duration = 0.0
    for window in windows:
        boundaries = window.get("boundaries") or (0.0, 0.0)
        offset = float(boundaries[0])
        seg_start = offset
        seg_end = float(boundaries[1])
        words = tuple(
            Word(
                word=str(w["text"]),
                start=offset + float(w["start"]),
                end=offset + float(w["end"]),
            )
            for w in window.get("words", ())
        )
        # ``transcription`` is the punctuated/normalized window text; carry it so the
        # worker recovers sentence boundaries (per-word tokens are un-punctuated).
        seg_text = str(window.get("transcription", "") or "")
        segments.append(Segment(start=seg_start, end=seg_end, words=words, text=seg_text))
        duration = max(duration, seg_end)
    return RawPayload(duration=duration, language=language, segments=tuple(segments))


def transcribe_with_model(model: _Longform, audio_path: str, language: str) -> RawPayload:
    """Run a (real or fake) longform model and map its output to the contract.

    Split from the default so the PURE mapping + error wrapping is unit-covered
    with a fake model, while the heavy real-model construction stays pragma'd.
    """
    try:
        windows = model.transcribe_longform(audio_path)
    except Exception as exc:  # noqa: BLE001 - normalize any model fault to our type
        raise TranscriptionError(f"gigaam transcribe_longform failed: {exc}") from exc
    return _map_longform_result(windows, language=language)


def payload_from_longform(result: object, *, language: str) -> RawPayload:
    """PURE: a GigaAM-v3 ``LongformTranscriptionResult`` (OBJECTS) → ``RawPayload``.

    This is the adapter for the REAL ``model.transcribe_longform(audio,
    word_timestamps=True)`` return shape, which differs from the dict shape
    ``_map_longform_result`` consumes in two ways verified against the upstream
    source:

      * It is an object graph, not dicts — ``result.segments`` is a list of
        ``Segment(text, start, end, words=[Word(text, start, end)])``.
      * Its segment AND word times are ALREADY ABSOLUTE (whole-media). Upstream
        ``transcribe_longform`` offsets each word by its VAD chunk's ``seg_start``
        before returning, so — unlike ``_map_longform_result`` — we add NO offset
        here (doing so would double-count and desync captions).

    Duck-typed on ``.segments`` / ``.start`` / ``.end`` / ``.text`` / ``.words``
    so it is unit-testable with a lightweight fake (no gigaam install in CI).
    """
    segments: list[Segment] = []
    duration = 0.0
    for seg in result.segments:  # type: ignore[attr-defined]
        words = tuple(
            Word(word=str(w.text), start=float(w.start), end=float(w.end))
            for w in (seg.words or ())
        )
        seg_end = float(seg.end)
        # ``seg.text`` is the model's PUNCTUATED/normalized segment text (the bare
        # per-word ``w.text`` tokens are NOT punctuated). Carry it verbatim so the
        # worker can recover sentence-end boundaries from real punctuation.
        seg_text = str(getattr(seg, "text", "") or "")
        segments.append(Segment(start=float(seg.start), end=seg_end, words=words, text=seg_text))
        duration = max(duration, seg_end)
    return RawPayload(duration=duration, language=language, segments=tuple(segments))


def _build_real_model() -> _Longform:  # pragma: no cover - GPU + gigaam weights
    """Load the GigaAM-v3 RNN-T E2E model with pyannote VAD (founder-gated)."""
    import gigaam  # type: ignore[import-not-found]

    # ``v3_e2e_rnnt`` is the multilingual E2E RNN-T checkpoint; ``transcribe_longform``
    # wires pyannote VAD windowing so a 2h source is chunked before inference.
    return gigaam.load_model("v3_e2e_rnnt")


def _default_transcribe_audio(  # pragma: no cover - GPU + gigaam weights
    audio_path: str, language: str
) -> RawPayload:
    """REAL default: construct the GPU model once, transcribe, map to contract."""
    model = _build_real_model()
    return transcribe_with_model(model, audio_path, language)


# The injected seam. Tests replace this with a fake returning a canned RawPayload.
TranscribeAudio = Callable[[str, str], RawPayload]
default_transcribe_audio: TranscribeAudio = _default_transcribe_audio


__all__ = [
    "LANGUAGE_RU",
    "TranscribeAudio",
    "TranscriptionError",
    "default_transcribe_audio",
    "payload_from_longform",
    "transcribe_with_model",
]
