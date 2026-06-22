"""Shared test doubles: fake HTTP poster, fake model, canned payload, workspace."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

from fliphouse_gigaam.contracts import RawPayload, Segment, Word


@dataclass(frozen=True)
class FakeResponse:
    """Minimal response with the only field sign_and_post inspects."""

    status_code: int


class FakePoster:
    """Records every POST so a test can re-verify body + headers; returns 2xx."""

    def __init__(self, status_code: int = 202, raises: Exception | None = None) -> None:
        self._status = status_code
        self._raises = raises
        self.calls: list[tuple[str, bytes, dict[str, str]]] = []

    def __call__(self, url: str, body: bytes, headers: dict[str, str]) -> FakeResponse:
        self.calls.append((url, body, headers))
        if self._raises is not None:
            raise self._raises
        return FakeResponse(self._status)


class FakeModel:
    """Stands in for a GigaAM model: returns canned longform windows or raises."""

    def __init__(self, windows: list[dict] | None = None, raises: Exception | None = None) -> None:
        self._windows = windows or []
        self._raises = raises
        self.seen_path: str | None = None

    def transcribe_longform(self, audio_path: str) -> list[dict]:
        self.seen_path = audio_path
        if self._raises is not None:
            raise self._raises
        return self._windows


def canned_payload() -> RawPayload:
    """A small but contract-complete RawPayload for orchestration tests."""
    return RawPayload(
        duration=2.0,
        language="ru",
        segments=(
            Segment(
                start=0.0,
                end=2.0,
                words=(
                    Word(word="привет", start=0.0, end=1.0),
                    Word(word="мир", start=1.0, end=2.0),
                ),
            ),
        ),
    )


@contextmanager
def fake_workspace(root: Path) -> Iterator[Path]:
    """A workspace context manager that yields a pre-made directory (no cleanup)."""
    yield root


def make_fetch(written: bytes = b"AUDIO"):
    """Build a fake fetch_audio that writes ``written`` to the dest path."""

    def fetch(audio_url: str, dest: Path) -> None:
        dest.write_bytes(written)

    return fetch
