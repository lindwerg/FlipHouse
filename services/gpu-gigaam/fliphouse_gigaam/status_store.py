"""In-memory status store for ``GET /status/<request_id>``.

SKELETON: a process-local dict. Production needs a DURABLE store (Redis/Postgres)
because the sweep polls status across restarts and multiple replicas — see README.
The store is injected into the app so a unit test drives status transitions with
a real instance and asserts what the sweep would observe.
"""

from __future__ import annotations

from dataclasses import dataclass

from .contracts import STATUS_FAILED, STATUS_PROCESSING, STATUS_SUCCEEDED


@dataclass(frozen=True)
class StatusRecord:
    """One request's terminal-or-in-flight state, as the sweep reads it."""

    request_id: str
    status: str
    error: str | None = None

    def to_dict(self) -> dict:
        body = {"request_id": self.request_id, "status": self.status}
        if self.error is not None:
            body["error"] = self.error
        return body


class InMemoryStatusStore:
    """Process-local request-id → StatusRecord map. NOT durable (see README)."""

    def __init__(self) -> None:
        self._records: dict[str, StatusRecord] = {}

    def mark_processing(self, request_id: str) -> None:
        self._records[request_id] = StatusRecord(request_id, STATUS_PROCESSING)

    def mark_succeeded(self, request_id: str) -> None:
        self._records[request_id] = StatusRecord(request_id, STATUS_SUCCEEDED)

    def mark_failed(self, request_id: str, error: str) -> None:
        self._records[request_id] = StatusRecord(request_id, STATUS_FAILED, error=error)

    def get(self, request_id: str) -> StatusRecord | None:
        return self._records.get(request_id)
