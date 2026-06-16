"""Cloud primary provider (target: GigaAM-v3 self-host on the GPU lane).

GigaAM-v3 (MIT, free weights, best Russian ~8.4 % WER, native Cyrillic word
timings) is the founder-chosen primary. It does NOT run on Railway (no GPU); the
real call goes through the submit-and-park webhook lane (doc 01 §3). That network
hop is the injected ``transport`` boundary — exactly the ``llm_fn`` /
``_run_audio_fn`` injection style — so this provider is fully exercised offline
with a fake transport, and the real webhook transport is wired (and validated on
``tinkov-plata.mp4`` behind ``@pytest.mark.live``) in a later step.

The transport returns the provider's raw payload ``{duration, segments:
[{start, end, words:[{word, start, end}]}]}``; :func:`normalize_segments` flattens
it into the canonical contract (the leading-space invariant absorbs GigaAM's
clean Cyrillic tokens).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping

from .normalize import normalize_segments
from .provider import Transcript

# transport(audio_ref, language) -> raw provider payload (dict). The submit-and-park
# webhook receiver is wired here in the runner step; tests pass a fake.
Transport = Callable[[str, str], Mapping]

DEFAULT_ENGINE = "gigaam-v3"


class CloudTranscriptionProvider:
    """Cloud provider satisfying :class:`TranscriptionProvider` via an injected transport."""

    def __init__(
        self,
        *,
        transport: Transport,
        language: str = "ru",
        engine: str = DEFAULT_ENGINE,
    ) -> None:
        self._transport = transport
        self._language = language
        self._engine = engine

    def transcribe(self, audio_ref: str, *, language: str | None = None) -> Transcript:
        lang = language or self._language
        payload = self._transport(audio_ref, lang)
        return normalize_segments(
            payload.get("segments", ()),
            duration=float(payload.get("duration", 0.0)),
            language=lang,
            engine=self._engine,
        )
