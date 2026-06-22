"""The ``fetch_audio`` seam — download ``audio_url`` to a local path for the model.

The DEFAULT (httpx streaming download) is ``# pragma: no cover`` — it is real
network I/O. Unit tests inject a fake fetcher that writes a canned file, so the
orchestration is covered without a live URL.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from .errors import AudioFetchError

# Injected seam: (audio_url, dest_path) -> None (writes the audio bytes to dest).
FetchAudio = Callable[[str, Path], None]

# Stream chunk size for the real download (256 KiB).
_CHUNK_BYTES = 256 * 1024
# Fetch ceiling for a long (≤2h) source on a fast link.
_FETCH_TIMEOUT_S = 30 * 60


def _default_fetch_audio(audio_url: str, dest: Path) -> None:  # pragma: no cover - network
    """Stream ``audio_url`` to ``dest``; raise :class:`AudioFetchError` on failure."""
    import httpx  # type: ignore[import-not-found]

    try:
        with httpx.stream("GET", audio_url, timeout=_FETCH_TIMEOUT_S) as response:
            response.raise_for_status()
            with dest.open("wb") as handle:
                for chunk in response.iter_bytes(_CHUNK_BYTES):
                    handle.write(chunk)
    except Exception as exc:
        raise AudioFetchError(f"failed to fetch audio_url: {exc}") from exc


default_fetch_audio: FetchAudio = _default_fetch_audio


__all__ = ["AudioFetchError", "FetchAudio", "default_fetch_audio"]
