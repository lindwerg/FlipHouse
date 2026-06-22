"""Orchestration — the full transcribe job, every boundary injected.

On ``/transcribe`` the app stores ``status=processing`` and schedules
:func:`run_transcription` (background). That function: fetch audio →
``transcribe_audio`` → build the success body → ``sign_and_post`` → mark
``succeeded``. ANY exception flips it to mark ``failed`` + ``sign_and_post`` the
failure body. Every seam (fetch, transcribe, poster, clock, workspace, store) is a
:class:`TranscribeDeps` field, so a unit test drives both the success and failure
paths with fakes and asserts the posted body + signature + status transitions.
"""

from __future__ import annotations

import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path

from .audio import FetchAudio, default_fetch_audio
from .callback import HttpPoster, build_failure_body, build_success_body, sign_and_post
from .contracts import SubmitRequest
from .errors import GigaamError
from .status_store import InMemoryStatusStore
from .transcribe import TranscribeAudio, default_transcribe_audio

# Local filename the fetched audio is written to inside the workspace.
_AUDIO_FILENAME = "audio_input"


@contextmanager
def _default_workspace() -> Iterator[Path]:  # pragma: no cover - real tmpdir I/O
    """A throwaway temp directory for the fetched audio (cleaned on exit)."""
    with tempfile.TemporaryDirectory(prefix="gigaam-") as tmp:
        yield Path(tmp)


def _default_now() -> int:  # pragma: no cover - wall clock
    return int(time.time())


@dataclass(frozen=True)
class TranscribeDeps:
    """Every impure boundary the job touches, injected for 100% unit coverage."""

    secret: str
    poster: HttpPoster
    store: InMemoryStatusStore = field(default_factory=InMemoryStatusStore)
    fetch_audio: FetchAudio = default_fetch_audio
    transcribe_audio: TranscribeAudio = default_transcribe_audio
    workspace: Callable[[], object] = _default_workspace
    now: Callable[[], int] = _default_now


def run_transcription(req: SubmitRequest, deps: TranscribeDeps) -> None:
    """Run the job to terminal state. NEVER raises — failures become a failure
    callback + ``status=failed`` so the sweep always sees a terminal record.

    The status is set to ``processing`` by the caller (the app, synchronously,
    before scheduling) so a ``GET /status`` immediately after the 202 is truthful.
    """
    try:
        with deps.workspace() as ws:
            audio_path = Path(ws) / _AUDIO_FILENAME
            deps.fetch_audio(req.audio_url, audio_path)
            payload = deps.transcribe_audio(str(audio_path), req.language)
        body = build_success_body(req.request_id, payload)
        sign_and_post(
            poster=deps.poster,
            secret=deps.secret,
            webhook_url=req.webhook_url,
            body=body,
            timestamp=str(deps.now()),
        )
        deps.store.mark_succeeded(req.request_id)
    except GigaamError as exc:
        _report_failure(req, deps, str(exc))
    except Exception as exc:  # noqa: BLE001 - any unexpected fault still terminates cleanly
        _report_failure(req, deps, f"unexpected error: {exc}")


def _report_failure(req: SubmitRequest, deps: TranscribeDeps, error: str) -> None:
    """Mark failed and best-effort POST the failure callback.

    If the failure callback ITSELF cannot be delivered we still record
    ``status=failed`` locally — the sweep's ``GET /status`` is the backstop, so a
    dead webhook never strands the request in ``processing``.
    """
    deps.store.mark_failed(req.request_id, error)
    body = build_failure_body(req.request_id, error)
    try:
        sign_and_post(
            poster=deps.poster,
            secret=deps.secret,
            webhook_url=req.webhook_url,
            body=body,
            timestamp=str(deps.now()),
        )
    except GigaamError:
        # Already marked failed above; the sweep will observe it via /status.
        pass
