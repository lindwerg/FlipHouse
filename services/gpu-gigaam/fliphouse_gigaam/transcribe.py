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
        segments.append(Segment(start=seg_start, end=seg_end, words=words))
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
    "transcribe_with_model",
]
